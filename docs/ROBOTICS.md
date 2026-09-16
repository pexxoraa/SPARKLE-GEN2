# Robotics

The safety architecture is SPARKLE → Robot Gateway → ROS2 → independent Safety Controller → robot. Software gates reject direct motor/PWM/joint-voltage commands, require approval for motion, and check an independent emergency-stop callback before action. Live robotics remains externally blocked until a ROS2 robot gateway, real target and independent e-stop are available.
