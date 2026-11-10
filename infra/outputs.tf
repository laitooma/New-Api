output "url" {
  description = "URL publique de l'API"
  value       = aws_lightsail_container_service.api.url
}

output "health_url" {
  description = "A ouvrir pour verifier que l'API repond"
  value       = "${trimsuffix(aws_lightsail_container_service.api.url, "/")}/health"
}
