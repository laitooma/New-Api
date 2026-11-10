variable "region" {
  description = "Region AWS (eu-west-3 = Paris)"
  type        = string
  default     = "eu-west-3"
}

variable "service_name" {
  description = "Nom du service Lightsail (minuscules, chiffres et tirets)"
  type        = string
  default     = "new-api"
}

variable "image" {
  description = "Image a deployer. Mettre un tag sha-xxxxxxx pour savoir exactement quel code tourne."
  type        = string
  default     = "ghcr.io/laitooma/new-api:latest"
}

variable "power" {
  description = "Taille des machines : nano est la moins chere"
  type        = string
  default     = "nano"

  validation {
    condition     = contains(["nano", "micro", "small", "medium", "large", "xlarge"], var.power)
    error_message = "power doit valoir nano, micro, small, medium, large ou xlarge."
  }
}

variable "scale" {
  description = "Nombre de copies du conteneur (le prix est multiplie d'autant)"
  type        = number
  default     = 1

  validation {
    condition     = var.scale >= 1 && var.scale <= 20
    error_message = "scale doit etre entre 1 et 20."
  }
}
