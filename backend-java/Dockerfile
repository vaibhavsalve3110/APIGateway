# Multi-stage build: Maven builds the jar, a JRE image runs it (multi-arch: x86 and Arm).
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q -DskipTests package

FROM eclipse-temurin:21-jre
# curl is not in the base image and the compose health check needs it; backend-node waits on that
# check before it starts, so without curl the whole stack stalls.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 apigw
WORKDIR /app
COPY --from=build /src/target/platform-backend-*.jar app.jar
USER apigw
EXPOSE 8088
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/app.jar"]
