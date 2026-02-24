# docker build -t sophon-get-info:v1 .
# sudo docker run -td --privileged=true -v /etc/localtime:/etc/localtime:ro -v /etc/timezone:/etc/timezone:ro -v /opt/sophon:/opt/sophon:ro -v /dev:/dev -v /etc/profile.d:/etc/profile.d:ro -v /etc/profile:/etc/profile:ro -v /etc/ld.so.conf.d:/etc/ld.so.conf.d:ro -v /sys:/sys:ro -p 9090:9090 --name sophon-get-info_container sophon-get-info:v1

# Build linux kernel general dockerfile configuration file
FROM alpine:latest

# add software
RUN apk add --no-cache procps ncurses-dev i2c-tools wget bash

# download get-info-exporter
RUN cd / && \
wget https://github.com/sophgo/sophon-tools/releases/download/v25.07.17/get-info-exporter --no-check-certificate && \
chmod +x /get-info-exporter

# Set the locale
ENV LANG=C.UTF-8

#ENV RUST_LOG=debug

ENTRYPOINT ["/get-info-exporter"]
