mkdir -p /etc/sophliteos/config /var/log/sophliteos /var/lib/sophliteos/db /data/sophliteos
rm -rf /var/lib/sophliteos/dist
cp -r dist /var/lib/sophliteos/

# cp config/sophliteos.yaml /etc/sophliteos/config
cp release_version.txt /var/lib/sophliteos
# cp database/sophliteos.db /var/lib/sophliteos/db

