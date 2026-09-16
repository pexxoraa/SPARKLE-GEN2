import unittest
from sparkle_gen2.ros2_live import ROS2ParameterSafetyController,TurtleSimROS2Node
from sparkle_gen2.ros2_adapter import ROS2GatewayAdapter

class CLI:
    def __init__(self):self.x=1.0;self.estop=False
    def run(self,args,timeout=10):
        if args[:2]==['node','list']:return '/turtlesim\n/sparkle_safety_controller'
        if args[:2]==['topic','echo']:return f'x: {self.x}\ny: 2.0\ntheta: 0.0\n'
        if args[:2]==['service','call']:self.x+=0.2;return 'ok'
        if args[:2]==['param','get']:
            if args[-1]=='estop_active':return f'Boolean value is: {str(self.estop)}'
            if args[-1]=='max_distance':return 'Double value is: 0.5'
            if args[-1]=='max_angle':return 'Double value is: 0.5'
        raise RuntimeError(args)

class Cycle36Tests(unittest.TestCase):
    def test_simulation_move_requires_independent_safety_and_pose_verification(self):
        cli=CLI();g=ROS2GatewayAdapter(TurtleSimROS2Node(cli),ROS2ParameterSafetyController(cli),allowed_actions={'status','move'});r=g.invoke('move',{'distance':.2,'angle':0});self.assertTrue(g.verify('move',r)['verified'])
        with self.assertRaises(PermissionError):g.invoke('raw_motor',{})
        with self.assertRaises(PermissionError):g.invoke('move',{'distance':.8,'angle':0})
    def test_estop_blocks_simulation_action(self):
        cli=CLI();cli.estop=True;g=ROS2GatewayAdapter(TurtleSimROS2Node(cli),ROS2ParameterSafetyController(cli))
        with self.assertRaisesRegex(RuntimeError,'emergency_stop'):g.invoke('move',{'distance':.1})
if __name__=='__main__':unittest.main()
