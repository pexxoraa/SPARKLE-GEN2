from __future__ import annotations

def main():
    import rclpy
    from rclpy.node import Node
    class SafetyNode(Node):
        def __init__(self):
            super().__init__('sparkle_safety_controller');self.declare_parameter('estop_active',False);self.declare_parameter('max_distance',0.5);self.declare_parameter('max_angle',0.5)
    rclpy.init();node=SafetyNode()
    try:rclpy.spin(node)
    finally:node.destroy_node();rclpy.shutdown()
if __name__=='__main__':main()
