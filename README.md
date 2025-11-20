# Deye Inverter

Deye Inverter Command Line Tool and Monitoring

To install the deye-agent package, first clone the repository:

   git clone https://github.com/khvalera/deye-agent.git

Then in the deye-agent directory, run:

   python3 setup.py install

Copy the directory to the system:

   etc/deye-agent
   etc/systemd/system

Start the systemd service:

   systemctl restart deye-agent.service
