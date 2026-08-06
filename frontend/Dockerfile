FROM node:18-alpine AS builder

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .
# Build-time API URL. CRA bakes REACT_APP_* vars into the static JS at build
# time, so this MUST be passed as a Docker build arg (not a runtime env var).
# Leave unset for the "auto" build, which falls back to detecting the
# current hostname with port 5100 (see src/services/api.js).
ARG REACT_APP_API_URL=""
ENV REACT_APP_API_URL=${REACT_APP_API_URL}
RUN npm run build

# Production stage
FROM node:18-alpine

WORKDIR /app

RUN npm install -g serve

COPY --from=builder /app/build ./build

EXPOSE 3000

CMD ["serve", "-s", "build", "-l", "3000"]
