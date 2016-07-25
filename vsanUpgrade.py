#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Copyright 2016 VMware, Inc.  All rights reserved.

This file includes sample code to upgrade the On-Disk Format from V2 to V3 for Virtual SAN 6.2.

The code has been tested with the following configuration

Testbed: One cluster with four hosts. Each host has one 50G SSD and two 100G SSD

Preconditions:

1. vCenter Server is version 6.0 Update 2

2. ESXi hosts have been upgraded to ESXi 6.0 Update 2 or greater from ESXi 6.0 Update 1

3. The Virtual SAN On-Disk Format has NOT been converted from Version 2.0 to Version 3.

Case1: Upgrade from On-Disk Format Version 2 to Version 3 
python vsanDeploy.py -s <VCENTERSERVER> -u user -p password --cluster <CLUSTER> - - reduceredundancy 

Case2: Upgrade from On-Disk Format Version 2 to Version 3 with reduced redundancy 
python vsanDeploy.py -s <VCENTERSERVER> -u user -p password --cluster <CLUSTER> -- reduceredundancy 

Case3: Upgrade from On-Disk Format Version 2 to Version 3 and enable Deduplication and Compression 
python vsanDeploy.py -s <VCENTERSERVER> -u user -p password --cluster <CLUSTER> -- enabledc
"""

__author__ = 'VMware, Inc'

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
import sys
import ssl
import atexit
import argparse
import getpass
import copy
# import the VSAN API python bindings
import vsanmgmtObjects
import vsanapiutils

def GetArgs():
   """
   Supports the command-line arguments listed below.
   """
   parser = argparse.ArgumentParser(
      description='Process args for VSAN SDK sample application')
   parser.add_argument('-s', '--host', required=True, action='store',
                       help='Remote host to connect to')
   parser.add_argument('-o', '--port', type=int, default=443, action='store',
                       help='Port to connect on')
   parser.add_argument('-u', '--user', required=True, action='store',
                       help='User name to use when connecting to host')
   parser.add_argument('-p', '--password', required=False, action='store',
                       help='Password to use when connecting to host')
   parser.add_argument('--cluster', dest='clusterName', metavar="CLUSTER",
                       default='VSAN-Cluster')
   parser.add_argument('--objupgrade', action='store_true',
                       help='After all disk groups have been updated, also upgrade all objects')
   parser.add_argument('--reduceredundancy', action='store_true',
                       help='Removes the need for one disk group worth of free space, '
                            'by allowing reduced redundancy during disk upgrade')
   parser.add_argument('--enabledc', action='store_true',
                       help='Enable deduplication and compression on the VSAN cluster')

   args = parser.parse_args()
   return args

def CollectMultiple(content, objects, parameters, handleNotFound=True):
   if len(objects) == 0:
      return {}
   result = None
   pc = content.propertyCollector
   propSet = [vim.PropertySpec(
      type=objects[0].__class__,
      pathSet=parameters
   )]

   while result == None and len(objects) > 0:
      try:
         objectSet = []
         for obj in objects:
            objectSet.append(vim.ObjectSpec(obj=obj))
         specSet = [vim.PropertyFilterSpec(objectSet=objectSet, propSet=propSet)]
         result = pc.RetrieveProperties(specSet=specSet)
      except vim.ManagedObjectNotFound as ex:
         objects.remove(ex.obj)
         result = None

   out = {}
   for x in result:
      out[x.obj] = {}
      for y in x.propSet:
         out[x.obj][y.name] = y.val
   return out

def getClusterInstance(clusterName, serviceInstance):
   content = serviceInstance.RetrieveContent()
   searchIndex = content.searchIndex
   datacenters = content.rootFolder.childEntity
   for datacenter in datacenters:
      cluster = searchIndex.FindChild(datacenter.hostFolder, clusterName)
      if cluster is not None:
         return cluster
   return None

#This function will compare VSAN disk version with latest supported disk version
#Suppose supportedVersion is 4 and current VSAN contain disk of version 3, the function will return true
def hasOlderVersionDisks(hostDiskMappings, supportedVersion):
   for hostDiskMappings in hostDiskMappings:
      for diskMapping in hostDiskMappings:
         if diskMapping.ssd.vsanDiskInfo.formatVersion < supportedVersion:
            return True
         for disk in diskMapping.nonSsd:
            if disk.vsanDiskInfo.formatVersion < supportedVersion:
               return True
   return False

# Start program
def main():
   args = GetArgs()
   if args.password:
      password = args.password
   else:
      password = getpass.getpass(prompt='Enter password for host %s and '
                                        'user %s: ' % (args.host, args.user))

   # For python 2.7.9 and later, the defaul SSL conext has more strict
   # connection handshaking rule. We may need turn of the hostname checking
   # and client side cert verification
   context = None
   if sys.version_info[:3] > (2, 7, 8):
      context = ssl.create_default_context()
      context.check_hostname = False
      context.verify_mode = ssl.CERT_NONE

   si = SmartConnect(host=args.host,
                     user=args.user,
                     pwd=password,
                     port=int(args.port),
                     sslContext=context)

   atexit.register(Disconnect, si)

   cluster = getClusterInstance(args.clusterName, si)

   vcMos = vsanapiutils.GetVsanVcMos(si._stub, context=context)

   vsanUpgradeSystem = vcMos['vsan-upgrade-systemex']
   supportedVersion = vsanUpgradeSystem.RetrieveSupportedVsanFormatVersion(cluster)
   print 'The highest Virtual SAN disk format version that given cluster supports is {}'.format(supportedVersion)

   vsanSystems = CollectMultiple(si.content, cluster.host,
                                    ['configManager.vsanSystem']).values()
   vsanClusterSystem = vcMos['vsan-cluster-config-system']
   diskMappings = CollectMultiple(si.content, [vsanSystem['configManager.vsanSystem'] for vsanSystem in vsanSystems],
                                    ['config.storageInfo.diskMapping']).values()

   diskMappings = [diskMapping['config.storageInfo.diskMapping'] for diskMapping in diskMappings]
   needsUpgrade = hasOlderVersionDisks(diskMappings, supportedVersion)

   if needsUpgrade:
      vsanConfig = vsanClusterSystem.VsanClusterGetConfig(cluster)

      autoClaimChanged = False
      if vsanConfig.defaultConfig.autoClaimStorage:
         print 'autoClaimStorage should be set to false before upgrade VSAN disks'
         autoClaimChanged = True
         vsanReconfigSpec = vim.VimVsanReconfigSpec(
            modify = True,
            vsanClusterConfig = vim.VsanClusterConfigInfo(
               defaultConfig = vim.VsanClusterConfigInfoHostDefaultInfo(
                  autoClaimStorage = False
               )
            )
         )
         task = vsanClusterSystem.VsanClusterReconfig(cluster, vsanReconfigSpec)
         vsanapiutils.WaitForTasks([task], si)

      try:
         print 'Perform VSAN upgrade preflight check'
         upgradeSpec = vim.VsanDiskFormatConversionSpec(
            dataEfficiencyConfig = vim.VsanDataEfficiencyConfig(
               compressionEnabled = args.enabledc,
               dedupEnabled = args.enabledc
            )
         )

         issues = vsanUpgradeSystem.PerformVsanUpgradePreflightCheckEx(cluster, spec = upgradeSpec).issues
         if issues:
            print 'Please fix the issues before upgrade VSAN'
            for issue in issues:
               print issue.msg
            return

         #If you change the dataEfficiency property, then you should call VSanClusterReconfig, which will upgrade disk version
         #automatically
         if args.enablededup != vsanConfig.dataEfficiencyConfig.dedupEnabled:
            upgradeSpec = vim.VimVsanReconfigSpec(
               modify = True,
               dataEfficiencyConfig = upgradeSpec.dataEfficiencyConfig
            )
            print 'call VSanClusterReconfig, which will upgrade disk version'
            task = vsanClusterSystem.VsanClusterReconfig(cluster, upgradeSpec)
         else:
            print 'call PerformVsanUpgradeEx to upgrade disk versions'
            task = vsanUpgradeSystem.PerformVsanUpgradeEx(cluster=cluster, performObjectUpgrade=args.objupgrade,
                                                  allowReducedRedundancy=args.reduceredundancy)
         print 'Wait for VSAN upgraded finished'
         vsanapiutils.WaitForTasks([task], si)
      finally:
         if autoClaimChanged:
            print 'Restore autoClaimStorage settings'
            vsanReconfigSpec.vsanClusterConfig.defaultConfig.autoClaimStorage = True
            task = vsanClusterSystem.VsanClusterReconfig(cluster, vsanReconfigSpec)
            vsanapiutils.WaitForTasks([task], si)
   else:
      print 'All disk version is {}, no upgrade needed'.format(supportedVersion)

# Start program
if __name__ == "__main__":
   main()
