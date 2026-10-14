FROM python:3.12-slim
ARG DEBIAN_MIRROR_HOST=deb.debian.org
# Test tooling only; no application configuration, host socket or data volume.
RUN echo '#!/bin/sh' > /usr/sbin/policy-rc.d && echo 'exit 101' >> /usr/sbin/policy-rc.d \
    && chmod 755 /usr/sbin/policy-rc.d \
    && sed -i "s|http://deb.debian.org|https://${DEBIAN_MIRROR_HOST}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 -o APT::Update::Error-Mode=any update \
    && DEBIAN_FRONTEND=noninteractive DPKG_DEB_THREADS_MAX=2 apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
       systemd openssh-server sudo tzdata \
    && (test -x /usr/bin/python3 || ln -s /usr/local/bin/python3 /usr/bin/python3)
CMD ["python", "/fixture/test_install_runtime_linux.py"]
