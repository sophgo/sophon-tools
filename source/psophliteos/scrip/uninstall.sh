#!/bin/sh

systemctl stop sophliteos
systemctl disable sophliteos
rm -rf /etc/sophliteos /var/lib/sophliteos /var/log/sophliteos /etc/systemd/system/sophliteos.service  /bin/sophliteos