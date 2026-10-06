from __future__ import annotations
from .manager import ConnectorAuthorizationMode,ConnectorCapability,ConnectorDescriptor,ConnectorManager,ConnectorOperationMode,ConnectorRecord
from ...policy import PolicyEngine
from .gmail_connector import GmailConnectorError,GmailCredentialSource,GmailReadAdapter
from .calendar_connector import CalendarConnectorError,CalendarCredentialSource,CalendarReadAdapter
from .drive_connector import DriveConnectorError,DriveCredentialSource,DriveReadAdapter
from .github_connector import GitHubConnectorError,GitHubCredentialSource,GitHubReadAdapter
from ...browser_orchestration import BrowserOrchestrator,BrowserOrchestrationError
from ..devices.linux_application import LinuxApplicationAdapter,LinuxApplicationError
from ..devices.computer_adapter import ComputerAdapter,ComputerAdapterError
from ..security.protected_secrets import protected_credential_file_refs
from .outlook_connector import OutlookCredentialSource,OutlookGraphAdapter,OutlookConnectorError
try:
    from sparkle.secrets import SecretResolver
except Exception:
    SecretResolver=None

def C(capability,operation,scope,mode='READ',policy=None,description=''):
    m=ConnectorOperationMode(mode);return ConnectorCapability(capability,operation,scope,m,policy or ('connector_read' if m==ConnectorOperationMode.READ else 'connector_write'),description)

DESCRIPTORS=(
 ConnectorDescriptor('gmail','Gmail','Google Gmail API',(C('gmail.read.list','list_messages','gmail.read','READ','gmail.read'),C('gmail.read.metadata','get_message_metadata','gmail.read','READ','gmail.read')),ConnectorAuthorizationMode.OAUTH,('SPARKLE_GMAIL_TOKEN_FILE',),'Google OAuth/Gmail account'),
 ConnectorDescriptor('outlook','Outlook','Microsoft Graph',(C('outlook.read','read','outlook.read'),C('outlook.draft','draft','outlook.draft','WRITE'),C('outlook.send','send','outlook.send','WRITE')),ConnectorAuthorizationMode.OAUTH,('MICROSOFT_GRAPH_TOKEN',),'Microsoft OAuth/account'),
 ConnectorDescriptor('calendar','Calendar','Google Calendar API',(C('calendar.read.list_calendars','list_calendars','calendar.read','READ','calendar.read'),C('calendar.read.list_events','list_events','calendar.read','READ','calendar.read'),C('calendar.read.get_event','get_event','calendar.read','READ','calendar.read')),ConnectorAuthorizationMode.OAUTH,('SPARKLE_CALENDAR_TOKEN_FILE',),'Google OAuth/Calendar account'),
 ConnectorDescriptor('drive','Drive','Google Drive API',(C('drive.read.list_files','list_files','drive.read','READ','drive.read'),C('drive.read.metadata','get_file_metadata','drive.read','READ','drive.read')),ConnectorAuthorizationMode.OAUTH,('SPARKLE_DRIVE_TOKEN_FILE',),'Google OAuth/Drive account'),
 ConnectorDescriptor('github','GitHub','GitHub API',(C('github.read.user','get_user','github.read','READ','github.read'),C('github.read.repositories','list_repositories','github.read','READ','github.read'),C('github.read.repository','get_repository','github.read','READ','github.read'),C('github.read.contents','list_repository_contents','github.read','READ','github.read'),C('github.read.issues','list_issues','github.read','READ','github.read'),C('github.read.pull_requests','list_pull_requests','github.read','READ','github.read'),C('github.read.workflows','list_workflows','github.read','READ','github.read')),ConnectorAuthorizationMode.SECRET,('SPARKLE_GITHUB_TOKEN_FILE',),'GitHub PAT/account'),
 ConnectorDescriptor('files','Files','SPARKLE workspace',(C('files.read','read','files.read','READ','file_read'),C('files.write','write','files.write','WRITE','connector_write')),ConnectorAuthorizationMode.NONE,(),None),
 ConnectorDescriptor('browser','Browser','SPARKLE Gen-1 BrowserSession',(C('browser.navigate','navigate','browser.navigate','READ','browser.navigate'),C('browser.read','read','browser.read','READ','browser.read'),C('browser.interact','interact','browser.interact','CONTROL','browser.interact')),ConnectorAuthorizationMode.EXTERNAL,(),'approved Gen-1 browser boundary',False),
 ConnectorDescriptor('linux','Linux','SPARKLE bounded Linux application boundary',(C('linux.inspect','inspect','linux.inspect','READ','linux.inspect'),C('linux.execute','execute','linux.execute','CONTROL','linux.execute')),ConnectorAuthorizationMode.EXTERNAL,(),'bounded local Linux execution boundary',True),
 ConnectorDescriptor('iot','IoT','IoT provider',(C('iot.discover','discover','iot.discover'),C('iot.read_state','read_state','iot.read_state'),C('iot.control','control','iot.control','CONTROL')),ConnectorAuthorizationMode.DEVICE,(),'authenticated IoT transport/device',True),
 ConnectorDescriptor('ros2','ROS 2','ROS 2 gateway',(C('ros2.discover','discover','robot.discover','READ','ros2_sim_status'),C('ros2.observe','observe','robot.status','READ','ros2_sim_status'),C('ros2.command','command','robot.move','CONTROL','ros2_sim_move')),ConnectorAuthorizationMode.NONE,(),'ROS 2 gateway/safety controller',True),
 # Legacy discoverable surfaces kept for compatibility; no new execution stacks are activated.
 ConnectorDescriptor('computer','Computer','XDG Desktop Portal (GNOME Wayland)',(C('computer.read','read','computer.read','READ','computer.read'),C('computer.act','act','computer.act','CONTROL','computer.act')),ConnectorAuthorizationMode.EXTERNAL,(),'GNOME Wayland XDG portal session',True),
 ConnectorDescriptor('esp32','ESP32','ESP32 transport',(C('esp32.read','read','esp32.read'),C('esp32.act','act','esp32.act','CONTROL')),ConnectorAuthorizationMode.DEVICE,(),'ESP32 device + authenticated transport',True),
 ConnectorDescriptor('mobile','Mobile','authenticated mobile device transport',(C('mobile.read','read','mobile.read','READ','mobile.read'),C('mobile.act','act','mobile.act','CONTROL','mobile.act')),ConnectorAuthorizationMode.DEVICE,(),'authenticated mobile target/emulator transport',True),
 ConnectorDescriptor('mqtt','MQTT','MQTT broker',(C('mqtt.read','read','mqtt.read'),C('mqtt.publish','publish','mqtt.publish','WRITE')),ConnectorAuthorizationMode.SECRET,('MQTT_TOKEN',),'MQTT broker/device credentials',True),
)

class Gen1ToolConnector:
    """Adapter over existing allowlisted Gen-1/Gen-2 gateway tools; never executes arbitrary tool names."""
    def __init__(self,gateway,operations):self.gateway=gateway;self.operations=dict(operations)
    def health(self):
        tools=set(self.gateway.health().get('tools',[]));missing=sorted(set(self.operations.values())-tools);return {'ok':not missing,'missing_tools':missing,'operations':sorted(self.operations)}
    def invoke(self,operation,payload):
        if operation not in self.operations:raise KeyError(operation)
        obs=self.gateway.invoke(self.operations[operation],payload)
        if not obs.ok:raise RuntimeError('gen1_connector_operation_failed')
        return {'output':obs.output,'verification':obs.verification,'tool':obs.tool}
    def verify(self,operation,result):
        if operation not in self.operations:return {'verified':False,'reason':'operation_not_allowlisted'}
        if not isinstance(result,dict) or result.get('tool')!=self.operations[operation]:return {'verified':False,'reason':'tool_identity_mismatch'}
        evidence=result.get('verification')
        if not isinstance(evidence,dict) or evidence.get('verified') is not True:return {'verified':False,'reason':'underlying_verification_failed','method':'Gen-1 verification evidence'}
        return {'verified':True,'method':'existing gateway tool result plus independent verification evidence','tool':result['tool'],'underlying':evidence}

def build_default_connectors(*,store=None,policy=None,gateway=None,secrets=None,owner_user_id='user',activate_external=False,mobile_adapter=None,iot_adapter=None,esp32_adapter=None,mqtt_adapter=None):
    m=ConnectorManager(store,policy=policy or PolicyEngine(),secrets=secrets or (SecretResolver() if SecretResolver is not None else None),default_owner=owner_user_id)
    for d in DESCRIPTORS:m.register_descriptor(d)
    if activate_external:
        protected_refs=protected_credential_file_refs()
        gmail=GmailReadAdapter(GmailCredentialSource(path=protected_refs.get('SPARKLE_GMAIL_TOKEN_FILE')));m._adapters['gmail']=gmail
        gmail_state=m._state('gmail',owner_user_id)
        if gmail_state.authorization_state.value!='REVOKED' and gmail.configured():
            try:
                auth=gmail.authorize();m.authorize('gmail',['gmail.read'],owner_user_id=owner_user_id,actor='google_oauth_credential_boundary',reference=auth['authorization_reference']);m.connect('gmail',owner_user_id=owner_user_id)
            except GmailConnectorError as exc:
                mapped={'AUTH_EXPIRED':'EXPIRED','AUTH_REVOKED':'REVOKED','AUTH_REQUIRED':'REQUIRED'}.get(exc.category,'FAILED');m.set_authorization_state('gmail',mapped,owner_user_id=owner_user_id,actor='google_oauth_credential_boundary')
        calendar=CalendarReadAdapter(CalendarCredentialSource(path=protected_refs.get('SPARKLE_CALENDAR_TOKEN_FILE')));m._adapters['calendar']=calendar
        calendar_state=m._state('calendar',owner_user_id)
        if calendar_state.authorization_state.value!='REVOKED' and calendar.configured():
            try:
                auth=calendar.authorize();m.authorize('calendar',['calendar.read'],owner_user_id=owner_user_id,actor='google_oauth_credential_boundary',reference=auth['authorization_reference']);m.connect('calendar',owner_user_id=owner_user_id)
            except CalendarConnectorError as exc:
                mapped={'AUTH_EXPIRED':'EXPIRED','AUTH_REVOKED':'REVOKED','AUTH_REQUIRED':'REQUIRED'}.get(exc.category,'FAILED');m.set_authorization_state('calendar',mapped,owner_user_id=owner_user_id,actor='google_oauth_credential_boundary')
        drive=DriveReadAdapter(DriveCredentialSource(path=protected_refs.get('SPARKLE_DRIVE_TOKEN_FILE')));m._adapters['drive']=drive
        drive_state=m._state('drive',owner_user_id)
        if drive_state.authorization_state.value!='REVOKED' and drive.configured():
            try:
                auth=drive.authorize();m.authorize('drive',['drive.read'],owner_user_id=owner_user_id,actor='google_oauth_credential_boundary',reference=auth['authorization_reference']);m.connect('drive',owner_user_id=owner_user_id)
            except DriveConnectorError as exc:
                mapped={'AUTH_EXPIRED':'EXPIRED','AUTH_REVOKED':'REVOKED','AUTH_REQUIRED':'REQUIRED'}.get(exc.category,'FAILED');m.set_authorization_state('drive',mapped,owner_user_id=owner_user_id,actor='google_oauth_credential_boundary')
        outlook=OutlookGraphAdapter(OutlookCredentialSource(m.secrets));m._adapters['outlook']=outlook
        outlook_state=m._state('outlook',owner_user_id)
        if outlook_state.authorization_state.value!='REVOKED' and outlook.configured():
            try:
                auth=outlook.authorize();m.authorize('outlook',['outlook.read','outlook.draft','outlook.send'],owner_user_id=owner_user_id,actor='microsoft_graph_credential_boundary',reference=auth['authorization_reference']);m.connect('outlook',owner_user_id=owner_user_id)
            except OutlookConnectorError as exc:
                mapped={'AUTH_REVOKED':'REVOKED','AUTH_REQUIRED':'REQUIRED'}.get(exc.category,'FAILED');m.set_authorization_state('outlook',mapped,owner_user_id=owner_user_id,actor='microsoft_graph_credential_boundary')
        github=GitHubReadAdapter(GitHubCredentialSource(path=protected_refs.get('SPARKLE_GITHUB_TOKEN_FILE')));m._adapters['github']=github
        github_state=m._state('github',owner_user_id)
        if github_state.authorization_state.value!='REVOKED' and github.configured():
            try:
                auth=github.authorize();m.authorize('github',['github.read'],owner_user_id=owner_user_id,actor='github_pat_credential_boundary',reference=auth['authorization_reference']);m.connect('github',owner_user_id=owner_user_id)
            except GitHubConnectorError as exc:
                mapped={'AUTH_REVOKED':'REVOKED','AUTH_REQUIRED':'REQUIRED'}.get(exc.category,'FAILED');m.set_authorization_state('github',mapped,owner_user_id=owner_user_id,actor='github_pat_credential_boundary')
    if mobile_adapter is not None and getattr(mobile_adapter,'configured',lambda:False)():
        mobile_state=m._state('mobile',owner_user_id)
        if mobile_state.authorization_state.value!='REVOKED':
            auth=mobile_adapter.authorize();m._adapters['mobile']=mobile_adapter;m.authorize('mobile',['mobile.read','mobile.act'],owner_user_id=owner_user_id,actor='authenticated_mobile_device_binding',reference=auth['authorization_reference']);m.connect('mobile',owner_user_id=owner_user_id)
    for connector_id,adapter,scopes,actor in (
        ('iot',iot_adapter,['iot.discover','iot.read_state','iot.control'],'authenticated_iot_device_binding'),
        ('esp32',esp32_adapter,['esp32.read','esp32.act'],'authenticated_iot_device_binding'),
        ('mqtt',mqtt_adapter,['mqtt.read','mqtt.publish'],'authenticated_mqtt_transport_binding'),
    ):
        if adapter is not None and getattr(adapter,'configured',lambda:False)():
            state=m._state(connector_id,owner_user_id)
            if state.authorization_state.value!='REVOKED':
                auth=adapter.authorize();m._adapters[connector_id]=adapter;m.authorize(connector_id,scopes,owner_user_id=owner_user_id,actor=actor,reference=auth['authorization_reference']);m.connect(connector_id,owner_user_id=owner_user_id)
    try:
        computer=ComputerAdapter(owner_user_id=owner_user_id);m._adapters['computer']=computer
        computer_state=m._state('computer',owner_user_id)
        if computer_state.authorization_state.value!='REVOKED' and computer.configured():
            auth=computer.authorize();m.authorize('computer',['computer.read','computer.act'],owner_user_id=owner_user_id,actor='xdg_portal_boundary',reference=auth['authorization_reference']);m.connect('computer',owner_user_id=owner_user_id)
    except (ComputerAdapterError,OSError,ValueError):
        pass
    try:
        linux=LinuxApplicationAdapter(owner_user_id=owner_user_id);m._adapters['linux']=linux
        linux_state=m._state('linux',owner_user_id)
        if linux_state.authorization_state.value!='REVOKED' and linux.configured():
            auth=linux.authorize();m.authorize('linux',['linux.inspect','linux.execute'],owner_user_id=owner_user_id,actor='local_linux_execution_boundary',reference=auth['authorization_reference']);m.connect('linux',owner_user_id=owner_user_id)
    except (LinuxApplicationError,OSError,ValueError):
        pass
    if gateway is not None:
        browser=BrowserOrchestrator(gateway,owner_user_id=owner_user_id);m._adapters['browser']=browser
        if browser.configured():
            try:
                auth=browser.authorize();m.authorize('browser',['browser.navigate','browser.read','browser.interact'],owner_user_id=owner_user_id,actor='gen1_browser_acceptance',reference=auth['authorization_reference']);m.connect('browser',owner_user_id=owner_user_id)
            except BrowserOrchestrationError:
                m.set_authorization_state('browser','FAILED',owner_user_id=owner_user_id,actor='gen1_browser_acceptance')
        tools=set(gateway.health().get('tools',[]))
        if 'file_read' in tools:
            a=Gen1ToolConnector(gateway,{'read':'file_read'});m._adapters['files']=a;m.connect('files',owner_user_id=owner_user_id)
        # ROS2 is exposed only through the already-safe gateway tools; no physical adapter is invented.
        ros_ops={}
        if 'ros2_sim_status' in tools:ros_ops.update({'discover':'ros2_sim_status','observe':'ros2_sim_status'})
        if 'ros2_sim_move' in tools:ros_ops['command']='ros2_sim_move'
        if ros_ops:
            a=Gen1ToolConnector(gateway,ros_ops);m._adapters['ros2']=a;m.connect('ros2',owner_user_id=owner_user_id)
    return m
