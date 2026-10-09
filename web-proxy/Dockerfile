FROM golang AS builder
WORKDIR /src/wrp
COPY . .
RUN go mod download
ARG TARGETARCH
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build -o /wrp-${TARGETARCH}

FROM chromedp/headless-shell
ARG TARGETARCH
COPY --from=builder /wrp-${TARGETARCH} /wrp
ENTRYPOINT ["/wrp"]
ENV PATH="/headless-shell:${PATH}"
LABEL maintainer="as@tenoware.com"
