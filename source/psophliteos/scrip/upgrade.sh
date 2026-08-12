mkdir -p /etc/sophliteos/config /var/log/sophliteos /var/lib/sophliteos/db /data/sophliteos

# 前端已内嵌进二进制，无需再部署 dist 目录。

# cp config/sophliteos.yaml /etc/sophliteos/config
cp release_version.txt /var/lib/sophliteos
# cp database/sophliteos.db /var/lib/sophliteos/db

