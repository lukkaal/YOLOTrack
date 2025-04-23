#!/usr/bin/env python3
import os
import launch
import launch_ros
from launch import LaunchDescription
from launch.launcher import DefaultLauncher
from launch.launch_context import LaunchContext
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory

def main():
    # 获取 example 包的路径
    example_pkg_path = get_package_share_directory('example')

    # 构建 launch 文件路径
    launch_file_path = os.path.join(example_pkg_path, 'launch', 'body_track.launch.py')

    # 创建 LaunchDescription 对象，包含要执行的 launch 文件
    launch_description = launch.LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(launch_file_path)
        )
    ])

    # 启动器
    launcher = launch.LaunchService()
    launcher.include_launch_description(launch_description)

    print(f"Launching {launch_file_path}...")
    launcher.run()

if __name__ == '__main__':
    main()
