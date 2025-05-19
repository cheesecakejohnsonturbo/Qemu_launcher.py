# Qemu_launcher.py
A simple launcher to setup and run, with limited options, virtual machines on windows QEMU. Should also work on linux, untested.
It will allow you to setup and configure multiple instances and select various iso, img files.
It's incomplete and lacks features but it should be enough to tinker with and get stuff working out the box.
I plan on adding more options later.
You can enter the name of the desired path to the qcow2 file you want to create in the virtual_machines_storage/ folder or you can use the same prompt to point to a pre-existing qcow2 file in the same folder to import a preexisting copy of a virtual machine.
It's not perfect and some things don't work, like audio.
