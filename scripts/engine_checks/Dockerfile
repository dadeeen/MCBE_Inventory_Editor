# Developer test host only; Mojang's server is supplied locally at run time.
FROM ubuntu:24.04@sha256:69cecf4bbf72d2d44a9eef1b71fb98c7fb973d78af11399deccef19beb008ad9
RUN apt-get update && apt-get install -y --no-install-recommends libcurl4 libssl3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV LD_LIBRARY_PATH=/server
WORKDIR /server
USER 10001:10001
ENTRYPOINT ["./bedrock_server"]
