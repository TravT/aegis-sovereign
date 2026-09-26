job "aegis-sovereign-appliance" {
  datacenters = ["dc1"]
  type        = "service"

  group "appliance" {
    count = 1

    network {
      mode = "bridge"
      port "http" {
        to = 8765
      }
      port "qdrant_http" {
        to = 6333
      }
      port "qdrant_grpc" {
        to = 6334
      }
    }

    # 1. Qdrant Vector Storage
    task "qdrant" {
      driver = "docker"

      config {
        image = "qdrant/qdrant:v1.12.1"
        volumes = [
          "/data/qdrant:/qdrant/storage"
        ]
      }

      resources {
        cpu    = 1000
        memory = 1536
      }
    }

    # 2. Sovereign Core Daemon
    task "core" {
      driver = "docker"

      config {
        image = "aegis-sovereign-core:latest"
        volumes = [
          "/data:/data",
          "/docs:/docs:ro"
        ]
      }

      env {
        SOVEREIGN_HOST          = "0.0.0.0"
        SOVEREIGN_PORT          = "8765"
        QDRANT_URL              = "http://127.0.0.1:6333"
        SOVEREIGN_COLLECTION    = "sovereign_chunks"
        SOVEREIGN_GRAPH_DB_PATH = "/data/rag/graph_store.db"
      }

      service {
        name = "sovereign-vault"
        port = "http"

        tags = [
          "traefik.enable=true",
          "traefik.http.routers.sovereign-vault.rule=Host(`sovereign-vault.home.arpa`)",
          "traefik.http.routers.sovereign-vault.entrypoints=websecure",
          "traefik.http.routers.sovereign-vault.tls=true"
        ]

        check {
          type     = "http"
          path     = "/health"
          interval = "10s"
          timeout  = "2s"
        }
      }

      resources {
        cpu    = 1500
        memory = 2048
      }
    }
  }
}
