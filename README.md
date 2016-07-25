This file includes sample code to upgrade the On-Disk Format from V2 to V3 for Virtual SAN 6.2.

The code has been tested with the following configuration

Testbed: One cluster with four hosts. Each host has one 50G SSD and two 100G SSD

Preconditions:

1. vCenter Server is version 6.0 Update 2

2. ESXi hosts have been upgraded to ESXi 6.0 Update 2 or greater from ESXi 6.0 Update 1

3. The Virtual SAN On-Disk Format has NOT been converted from Version 2.0 to Version 3.

Case1: Upgrade from On-Disk Format Version 2 to Version 3 
python vsanDeploy.py -s <VCENTERSERVER> -u user -p password --cluster <CLUSTER> --reduceredundancy 

Case2: Upgrade from On-Disk Format Version 2 to Version 3 with reduced redundancy 
python vsanDeploy.py -s <VCENTERSERVER> -u user -p password --cluster <CLUSTER> --reduceredundancy 

Case3: Upgrade from On-Disk Format Version 2 to Version 3 and enable Deduplication and Compression 
python vsanDeploy.py -s <VCENTERSERVER> -u user -p password --cluster <CLUSTER> --enabledc
