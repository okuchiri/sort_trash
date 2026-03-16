from pyAgxArm import create_agx_arm_config, AgxArmFactory

cfg = create_agx_arm_config(robot="nero", comm="can", channel="can0")
robot = AgxArmFactory.create_arm(cfg)
robot.connect()

robot.set_normal_mode()