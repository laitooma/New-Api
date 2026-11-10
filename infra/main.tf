# Service de conteneurs Lightsail : une URL HTTPS publique, prix fixe,
# sans reseau (VPC) ni load balancer a configurer.
resource "aws_lightsail_container_service" "api" {
  name  = var.service_name
  power = var.power
  scale = var.scale

  tags = {
    project = "new-api"
  }
}

# Ce qui tourne dans le service : l'image publiee par la CI sur ghcr.io
resource "aws_lightsail_container_service_deployment_version" "api" {
  service_name = aws_lightsail_container_service.api.name

  container {
    container_name = "api"
    image          = var.image

    ports = {
      8000 = "HTTP"
    }
  }

  public_endpoint {
    container_name = "api"
    container_port = 8000

    # Lightsail remplace le conteneur s'il ne repond plus sur /health
    health_check {
      path                = "/health"
      success_codes       = "200"
      interval_seconds    = 10
      timeout_seconds     = 5
      healthy_threshold   = 2
      unhealthy_threshold = 3
    }
  }
}
