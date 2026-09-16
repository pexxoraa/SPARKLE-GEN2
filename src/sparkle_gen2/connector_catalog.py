from __future__ import annotations
from .connectors import ConnectorManager,ConnectorRecord

EXTERNAL_CONNECTORS={
 'gmail':(['gmail.read','gmail.draft','gmail.send'],'Google OAuth/account'),
 'outlook':(['outlook.read','outlook.draft','outlook.send'],'Microsoft OAuth/account'),
 'calendar':(['calendar.read','calendar.create'],'Calendar OAuth/account'),
 'drive':(['drive.read','drive.write'],'Drive OAuth/account'),
 'github':(['github.read','github.write'],'GitHub authorization/token'),
 'browser':(['browser.read','browser.act'],'approved browser control environment'),
 'computer':(['computer.read','computer.act'],'approved GUI/computer-control environment'),
 'linux':(['linux.read','linux.act'],'approved Linux application-control environment'),
 'files':(['files.read','files.write'],'authorized filesystem boundary'),
 'esp32':(['esp32.read','esp32.act'],'ESP32 device + authenticated transport'),
 'mobile':(['mobile.read','mobile.act'],'mobile target/emulator'),
 'mqtt':(['mqtt.read','mqtt.publish'],'MQTT broker/device credentials'),
 'ros2':(['robot.status','robot.move'],'ROS 2 robot gateway + safety controller'),
}

def build_default_connectors():
    m=ConnectorManager()
    for name,(scopes,dependency) in EXTERNAL_CONNECTORS.items():m.register(ConnectorRecord(name,list(scopes),'BLOCKED',external_dependency=dependency))
    return m

class Gen1ToolConnector:
    def __init__(self,gateway,operations):self.gateway=gateway;self.operations=dict(operations)
    def health(self):
        tools=set(self.gateway.health().get('tools',[]));missing=sorted(set(self.operations.values())-tools)
        return {'ok':not missing,'missing_tools':missing}
    def invoke(self,operation,payload):
        if operation not in self.operations:raise KeyError(operation)
        obs=self.gateway.invoke(self.operations[operation],payload)
        if not obs.ok:raise RuntimeError('gen1_connector_operation_failed')
        return {'output':obs.output,'verification':obs.verification,'tool':obs.tool}
