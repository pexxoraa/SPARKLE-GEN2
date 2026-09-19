from __future__ import annotations
from .connectors import ConnectorAuthorizationMode,ConnectorCapability,ConnectorDescriptor,ConnectorManager,ConnectorOperationMode,ConnectorRecord
from .policy import PolicyEngine
try:
    from sparkle.secrets import SecretResolver
except Exception:
    SecretResolver=None

def C(capability,operation,scope,mode='READ',policy=None,description=''):
    m=ConnectorOperationMode(mode);return ConnectorCapability(capability,operation,scope,m,policy or ('connector_read' if m==ConnectorOperationMode.READ else 'connector_write'),description)

DESCRIPTORS=(
 ConnectorDescriptor('gmail','Gmail','Google Gmail',(C('gmail.read','read','gmail.read'),C('gmail.draft','draft','gmail.draft','WRITE'),C('gmail.send','send','gmail.send','WRITE')),ConnectorAuthorizationMode.OAUTH,('GOOGLE_OAUTH_TOKEN',),'Google OAuth/account'),
 ConnectorDescriptor('outlook','Outlook','Microsoft Graph',(C('outlook.read','read','outlook.read'),C('outlook.draft','draft','outlook.draft','WRITE'),C('outlook.send','send','outlook.send','WRITE')),ConnectorAuthorizationMode.OAUTH,('MICROSOFT_GRAPH_TOKEN',),'Microsoft OAuth/account'),
 ConnectorDescriptor('calendar','Calendar','Calendar provider',(C('calendar.read','read','calendar.read'),C('calendar.create','create','calendar.create','WRITE'),C('calendar.delete','delete','calendar.delete','WRITE')),ConnectorAuthorizationMode.OAUTH,('CALENDAR_OAUTH_TOKEN',),'calendar OAuth/account'),
 ConnectorDescriptor('drive','Drive','Drive provider',(C('drive.read','read','drive.read'),C('drive.write','write','drive.write','WRITE')),ConnectorAuthorizationMode.OAUTH,('DRIVE_OAUTH_TOKEN',),'Drive OAuth/account'),
 ConnectorDescriptor('github','GitHub','GitHub',(C('github.read','read','github.read'),C('github.create_branch','create_branch','github.create_branch','WRITE'),C('github.commit','commit','github.commit','WRITE'),C('github.push','push','github.push','WRITE')),ConnectorAuthorizationMode.SECRET,('GITHUB_TOKEN',),'GitHub authorization/token'),
 ConnectorDescriptor('files','Files','SPARKLE workspace',(C('files.read','read','files.read','READ','file_read'),C('files.write','write','files.write','WRITE','connector_write')),ConnectorAuthorizationMode.NONE,(),None),
 ConnectorDescriptor('browser','Browser','SPARKLE browser boundary',(C('browser.navigate','navigate','browser.navigate'),C('browser.read','read','browser.read'),C('browser.interact','interact','browser.interact','CONTROL')),ConnectorAuthorizationMode.EXTERNAL,(),'approved browser control environment',True),
 ConnectorDescriptor('linux','Linux','SPARKLE Linux application boundary',(C('linux.inspect','inspect','linux.inspect'),C('linux.execute','execute','linux.execute','CONTROL')),ConnectorAuthorizationMode.EXTERNAL,(),'approved Linux application-control adapter',True),
 ConnectorDescriptor('iot','IoT','IoT provider',(C('iot.discover','discover','iot.discover'),C('iot.read_state','read_state','iot.read_state'),C('iot.control','control','iot.control','CONTROL')),ConnectorAuthorizationMode.DEVICE,(),'authenticated IoT transport/device',True),
 ConnectorDescriptor('ros2','ROS 2','ROS 2 gateway',(C('ros2.discover','discover','robot.discover','READ','ros2_sim_status'),C('ros2.observe','observe','robot.status','READ','ros2_sim_status'),C('ros2.command','command','robot.move','CONTROL','ros2_sim_move')),ConnectorAuthorizationMode.NONE,(),'ROS 2 gateway/safety controller',True),
 # Legacy discoverable surfaces kept for compatibility; no new execution stacks are activated.
 ConnectorDescriptor('computer','Computer','GUI control boundary',(C('computer.read','read','computer.read'),C('computer.act','act','computer.act','CONTROL')),ConnectorAuthorizationMode.EXTERNAL,(),'approved GUI/computer-control environment',True),
 ConnectorDescriptor('esp32','ESP32','ESP32 transport',(C('esp32.read','read','esp32.read'),C('esp32.act','act','esp32.act','CONTROL')),ConnectorAuthorizationMode.DEVICE,(),'ESP32 device + authenticated transport',True),
 ConnectorDescriptor('mobile','Mobile','mobile target',(C('mobile.read','read','mobile.read'),C('mobile.act','act','mobile.act','CONTROL')),ConnectorAuthorizationMode.DEVICE,(),'mobile target/emulator',True),
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

def build_default_connectors(*,store=None,policy=None,gateway=None,secrets=None,owner_user_id='user'):
    m=ConnectorManager(store,policy=policy or PolicyEngine(),secrets=secrets or (SecretResolver() if SecretResolver is not None else None),default_owner=owner_user_id)
    for d in DESCRIPTORS:m.register_descriptor(d)
    if gateway is not None:
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
