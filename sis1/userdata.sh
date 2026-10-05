#!/bin/bash
set -euxo pipefail
exec > >(tee /var/log/cad-userdata.log) 2>&1
dnf -y install nginx

cat > /usr/local/bin/cad-gen-index.sh <<'SCRIPT'
#!/bin/bash
MD=http://169.254.169.254/latest
TOKEN=$(curl -sX PUT "$MD/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
get() { curl -s -H "X-aws-ec2-metadata-token: $TOKEN" "$MD/meta-data/$1"; }
IID=$(get instance-id); AZ=$(get placement/availability-zone)
PRIV=$(get local-ipv4); MAC=$(get network/interfaces/macs/ | head -1)
SUBNET=$(get "network/interfaces/macs/${MAC}subnet-id"); VPCID=$(get "network/interfaces/macs/${MAC}vpc-id")
PUB=$(curl -s -m 2 -H "X-aws-ec2-metadata-token: $TOKEN" "$MD/meta-data/public-ipv4" || true)
[ -z "$PUB" ] && PUB="none - this host has no public address"
cat > /usr/share/nginx/html/index.html <<HTML
<!doctype html><html><head><meta charset="utf-8"><title>SIS 1 application tier</title><style>
body{font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;background:#f3f5f7;margin:0;
     display:flex;align-items:center;justify-content:center;min-height:100vh;color:#232F3E}
.card{background:#fff;border-radius:16px;box-shadow:0 10px 34px rgba(35,47,62,.14);padding:42px 54px;max-width:700px}
.pill{display:inline-block;background:#FF9900;color:#232F3E;font-weight:700;border-radius:999px;padding:6px 16px;font-size:13px}
h1{margin:14px 0 6px;font-size:27px}p.sub{color:#6b7280;margin:0 0 24px;font-size:15px}
table{border-collapse:collapse;width:100%}td{padding:9px 0;border-bottom:1px solid #eceff2;font-size:15px}
td.k{color:#6b7280;width:240px}td.v{font-family:ui-monospace,Menlo,monospace}
</style></head><body><div class="card">
<span class="pill">Private subnet &middot; reached only through the load balancer</span>
<h1>SIS 1 application tier</h1>
<p class="sub">This host has no public IP address and no inbound route from the internet. The load balancer in the public tier is the only thing its security group accepts traffic from.</p>
<table>
<tr><td class="k">Instance ID</td><td class="v">$IID</td></tr>
<tr><td class="k">Availability Zone</td><td class="v">$AZ</td></tr>
<tr><td class="k">VPC</td><td class="v">$VPCID</td></tr>
<tr><td class="k">Subnet</td><td class="v">$SUBNET</td></tr>
<tr><td class="k">Private IPv4</td><td class="v">$PRIV</td></tr>
<tr><td class="k">Public IPv4</td><td class="v">$PUB</td></tr>
<tr><td class="k">Page generated at</td><td class="v">$(date -u '+%Y-%m-%d %H:%M:%S UTC')</td></tr>
</table></div></body></html>
HTML
echo ok > /usr/share/nginx/html/health
SCRIPT
chmod +x /usr/local/bin/cad-gen-index.sh

cat > /etc/systemd/system/cad-index.service <<'UNIT'
[Unit]
Description=Generate the SIS1 identity page from instance metadata
After=network-online.target
Wants=network-online.target
Before=nginx.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/cad-gen-index.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable cad-index.service nginx
systemctl start cad-index.service nginx
echo "CAD SIS1 user data finished at $(date -u)"
