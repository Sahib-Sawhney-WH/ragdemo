#!/usr/bin/env python3
"""
Azure Container Instance Deployment Script for ExponentHR RAG Solution
Deploys the containerized RAG solution to Azure Container Instances.
"""

import json
import logging
import os
import subprocess
import sys
import time
import argparse
from typing import Dict, Optional
from datetime import datetime


class ACIDeploymentManager:
    """
    Deployment manager for Azure Container Instances.
    Handles container building, registry operations, and ACI deployment.
    """
    
    def __init__(self, config_file: str):
        """
        Initialize the ACI deployment manager.
        
        Args:
            config_file: Path to deployment configuration file
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.logger = self._setup_logging()
        
        # Deployment configuration
        self.container_name = self.config.get('container_name', 'exponenthr-rag-container')
        self.resource_group = self.config['azure_resource_group']
        self.registry_name = self.config.get('azure_container_registry', f"{self.config['azure_storage_account_name']}acr")
        self.image_name = f"{self.registry_name}.azurecr.io/exponenthr-rag:latest"
        
        # Container configuration
        self.cpu_cores = self.config.get('container_cpu_cores', 2)
        self.memory_gb = self.config.get('container_memory_gb', 4)
        self.restart_policy = self.config.get('container_restart_policy', 'Always')
        
    def _load_config(self) -> Dict:
        """Load deployment configuration from file"""
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            return config
        except Exception as e:
            print(f"Error loading config file {self.config_file}: {str(e)}")
            sys.exit(1)
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('ACIDeploymentManager')
        logger.setLevel(logging.INFO)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # File handler
        log_file = f"aci_deployment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(console_formatter)
        logger.addHandler(file_handler)
        
        return logger
    
    def deploy(self) -> bool:
        """
        Execute the complete ACI deployment process.
        
        Returns:
            True if deployment successful, False otherwise
        """
        self.logger.info("Starting Azure Container Instance deployment")
        
        try:
            # Step 1: Validate prerequisites
            self._validate_prerequisites()
            
            # Step 2: Create Azure resources (if needed)
            self._create_azure_resources()
            
            # Step 3: Create Azure Container Registry
            self._create_container_registry()
            
            # Step 4: Build and push container image
            self._build_and_push_image()
            
            # Step 5: Deploy to Azure Container Instances
            self._deploy_to_aci()
            
            # Step 6: Configure networking and DNS
            self._configure_networking()
            
            # Step 7: Verify deployment
            self._verify_deployment()
            
            self.logger.info("ACI deployment completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"ACI deployment failed: {str(e)}")
            return False
    
    def _validate_prerequisites(self) -> None:
        """Validate deployment prerequisites"""
        self.logger.info("Validating prerequisites...")
        
        # Check Docker
        try:
            result = subprocess.run(['docker', '--version'], capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception("Docker not found or not working")
            self.logger.info(f"Docker version: {result.stdout.strip()}")
        except FileNotFoundError:
            raise Exception("Docker is not installed")
        
        # Check Azure CLI
        try:
            result = subprocess.run(['az', '--version'], capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception("Azure CLI not found or not working")
        except FileNotFoundError:
            raise Exception("Azure CLI is not installed")
        
        # Check Azure login
        try:
            result = subprocess.run(['az', 'account', 'show'], capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception("Not logged into Azure CLI. Run 'az login' first.")
        except Exception:
            raise Exception("Azure CLI authentication check failed")
        
        # Check required files
        required_files = [
            'Dockerfile',
            'requirements.txt',
            'exponenthr_scraper.py',
            'azure_search_integration.py',
            'rag_orchestrator.py'
        ]
        
        for file_path in required_files:
            if not os.path.exists(file_path):
                raise Exception(f"Required file not found: {file_path}")
        
        self.logger.info("Prerequisites validated successfully")
    
    def _create_azure_resources(self) -> None:
        """Create required Azure resources"""
        self.logger.info("Creating Azure resources...")
        
        subscription_id = self.config['azure_subscription_id']
        resource_group = self.config['azure_resource_group']
        region = self.config['azure_region']
        
        try:
            # Create resource group
            self.logger.info(f"Creating resource group: {resource_group}")
            cmd = [
                'az', 'group', 'create',
                '--name', resource_group,
                '--location', region,
                '--subscription', subscription_id
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 and "already exists" not in result.stderr:
                raise Exception(f"Failed to create resource group: {result.stderr}")
            
            # Create storage account (if not exists)
            storage_account = self.config['azure_storage_account_name']
            self.logger.info(f"Ensuring storage account exists: {storage_account}")
            cmd = [
                'az', 'storage', 'account', 'create',
                '--name', storage_account,
                '--resource-group', resource_group,
                '--location', region,
                '--sku', 'Standard_LRS',
                '--subscription', subscription_id
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 and "already exists" not in result.stderr:
                self.logger.warning(f"Storage account creation warning: {result.stderr}")
            
            # Create search service (if not exists)
            search_service = self.config['azure_search_service_name']
            search_sku = self.config.get('azure_search_sku', 'basic')
            self.logger.info(f"Ensuring search service exists: {search_service}")
            cmd = [
                'az', 'search', 'service', 'create',
                '--name', search_service,
                '--resource-group', resource_group,
                '--location', region,
                '--sku', search_sku,
                '--subscription', subscription_id
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 and "already exists" not in result.stderr:
                self.logger.warning(f"Search service creation warning: {result.stderr}")
            
            self.logger.info("Azure resources created/verified successfully")
            
        except Exception as e:
            raise Exception(f"Failed to create Azure resources: {str(e)}")
    
    def _create_container_registry(self) -> None:
        """Create Azure Container Registry"""
        self.logger.info("Creating Azure Container Registry...")
        
        try:
            # Create ACR
            cmd = [
                'az', 'acr', 'create',
                '--name', self.registry_name,
                '--resource-group', self.resource_group,
                '--sku', 'Basic',
                '--admin-enabled', 'true'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 and "already exists" not in result.stderr:
                raise Exception(f"Failed to create container registry: {result.stderr}")
            
            self.logger.info(f"Container registry created/verified: {self.registry_name}")
            
        except Exception as e:
            raise Exception(f"Failed to create container registry: {str(e)}")
    
    def _build_and_push_image(self) -> None:
        """Build and push container image"""
        self.logger.info("Building and pushing container image...")
        
        try:
            # Login to ACR
            self.logger.info("Logging into Azure Container Registry...")
            cmd = ['az', 'acr', 'login', '--name', self.registry_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Failed to login to ACR: {result.stderr}")
            
            # Build image
            self.logger.info("Building Docker image...")
            cmd = [
                'docker', 'build',
                '-t', self.image_name,
                '.'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Failed to build Docker image: {result.stderr}")
            
            # Push image
            self.logger.info("Pushing image to registry...")
            cmd = ['docker', 'push', self.image_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Failed to push image: {result.stderr}")
            
            self.logger.info(f"Image built and pushed successfully: {self.image_name}")
            
        except Exception as e:
            raise Exception(f"Failed to build and push image: {str(e)}")
    
    def _deploy_to_aci(self) -> None:
        """Deploy container to Azure Container Instances"""
        self.logger.info("Deploying to Azure Container Instances...")
        
        try:
            # Get ACR credentials
            cmd = [
                'az', 'acr', 'credential', 'show',
                '--name', self.registry_name,
                '--query', 'username',
                '--output', 'tsv'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Failed to get ACR username: {result.stderr}")
            acr_username = result.stdout.strip()
            
            cmd = [
                'az', 'acr', 'credential', 'show',
                '--name', self.registry_name,
                '--query', 'passwords[0].value',
                '--output', 'tsv'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Failed to get ACR password: {result.stderr}")
            acr_password = result.stdout.strip()
            
            # Prepare environment variables
            env_vars = [
                f"AZURE_STORAGE_ACCOUNT_URL=https://{self.config['azure_storage_account_name']}.blob.core.windows.net",
                f"AZURE_SEARCH_ENDPOINT=https://{self.config['azure_search_service_name']}.search.windows.net",
                f"AZURE_SEARCH_INDEX_NAME={self.config.get('search_index_name', 'exponenthr-docs')}",
                f"OPENAI_API_KEY={self.config['openai_api_key']}",
                f"CONTENT_CONTAINER={self.config.get('content_container', 'scraped-content')}",
                f"REQUEST_DELAY={self.config.get('request_delay', 1.0)}",
                f"SYNC_BATCH_SIZE={self.config.get('sync_batch_size', 20)}"
            ]
            
            # Create ACI deployment
            cmd = [
                'az', 'container', 'create',
                '--name', self.container_name,
                '--resource-group', self.resource_group,
                '--image', self.image_name,
                '--cpu', str(self.cpu_cores),
                '--memory', str(self.memory_gb),
                '--registry-login-server', f"{self.registry_name}.azurecr.io",
                '--registry-username', acr_username,
                '--registry-password', acr_password,
                '--dns-name-label', self.container_name,
                '--ports', '5000',
                '--restart-policy', self.restart_policy,
                '--environment-variables'
            ] + env_vars
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Failed to create ACI: {result.stderr}")
            
            self.logger.info(f"Container deployed successfully: {self.container_name}")
            
        except Exception as e:
            raise Exception(f"Failed to deploy to ACI: {str(e)}")
    
    def _configure_networking(self) -> None:
        """Configure networking and DNS"""
        self.logger.info("Configuring networking...")
        
        try:
            # Get container details
            cmd = [
                'az', 'container', 'show',
                '--name', self.container_name,
                '--resource-group', self.resource_group,
                '--query', 'ipAddress.fqdn',
                '--output', 'tsv'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                fqdn = result.stdout.strip()
                self.logger.info(f"Container FQDN: {fqdn}")
                
                # Save endpoint information
                endpoint_info = {
                    'fqdn': fqdn,
                    'url': f"http://{fqdn}:5000",
                    'health_check': f"http://{fqdn}:5000/api/health",
                    'api_docs': f"http://{fqdn}:5000/api/system/status"
                }
                
                with open('aci_endpoints.json', 'w') as f:
                    json.dump(endpoint_info, f, indent=2)
                
                self.logger.info(f"Endpoint information saved to aci_endpoints.json")
            
        except Exception as e:
            self.logger.warning(f"Failed to configure networking: {str(e)}")
    
    def _verify_deployment(self) -> None:
        """Verify the deployment is working"""
        self.logger.info("Verifying deployment...")
        
        try:
            # Check container status
            cmd = [
                'az', 'container', 'show',
                '--name', self.container_name,
                '--resource-group', self.resource_group,
                '--query', 'instanceView.state',
                '--output', 'tsv'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                state = result.stdout.strip()
                self.logger.info(f"Container state: {state}")
                
                if state == "Running":
                    self.logger.info("Container is running successfully")
                else:
                    self.logger.warning(f"Container is not running. State: {state}")
            
            # Wait for container to be ready
            self.logger.info("Waiting for container to be ready...")
            time.sleep(30)
            
            # Check logs
            cmd = [
                'az', 'container', 'logs',
                '--name', self.container_name,
                '--resource-group', self.resource_group,
                '--tail', '20'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                self.logger.info("Recent container logs:")
                for line in result.stdout.split('\n')[-10:]:
                    if line.strip():
                        self.logger.info(f"  {line}")
            
        except Exception as e:
            self.logger.warning(f"Failed to verify deployment: {str(e)}")
    
    def get_deployment_info(self) -> Dict:
        """Get deployment information"""
        try:
            # Get container details
            cmd = [
                'az', 'container', 'show',
                '--name', self.container_name,
                '--resource-group', self.resource_group
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                container_info = json.loads(result.stdout)
                
                return {
                    'container_name': self.container_name,
                    'resource_group': self.resource_group,
                    'state': container_info.get('instanceView', {}).get('state'),
                    'fqdn': container_info.get('ipAddress', {}).get('fqdn'),
                    'ip': container_info.get('ipAddress', {}).get('ip'),
                    'ports': container_info.get('ipAddress', {}).get('ports', []),
                    'image': container_info.get('containers', [{}])[0].get('image'),
                    'cpu': container_info.get('containers', [{}])[0].get('resources', {}).get('requests', {}).get('cpu'),
                    'memory': container_info.get('containers', [{}])[0].get('resources', {}).get('requests', {}).get('memoryInGB')
                }
        except Exception as e:
            self.logger.error(f"Failed to get deployment info: {str(e)}")
            return {}
    
    def generate_deployment_report(self) -> str:
        """Generate deployment report"""
        deployment_info = self.get_deployment_info()
        
        report = f"""
ExponentHR RAG Solution - Azure Container Instance Deployment Report
==================================================================

Deployment Details:
  Container Name: {deployment_info.get('container_name', 'N/A')}
  Resource Group: {deployment_info.get('resource_group', 'N/A')}
  State: {deployment_info.get('state', 'N/A')}
  
Network Configuration:
  FQDN: {deployment_info.get('fqdn', 'N/A')}
  IP Address: {deployment_info.get('ip', 'N/A')}
  Ports: {deployment_info.get('ports', 'N/A')}

Container Configuration:
  Image: {deployment_info.get('image', 'N/A')}
  CPU: {deployment_info.get('cpu', 'N/A')} cores
  Memory: {deployment_info.get('memory', 'N/A')} GB

Access URLs:
  Application: http://{deployment_info.get('fqdn', 'N/A')}:5000
  Health Check: http://{deployment_info.get('fqdn', 'N/A')}:5000/api/health
  System Status: http://{deployment_info.get('fqdn', 'N/A')}:5000/api/system/status

Next Steps:
1. Test the health check endpoint
2. Verify Azure AI Search index is created
3. Connect Copilot Studio to the Azure AI Search index
4. Configure scheduled synchronization
5. Monitor container logs and performance

Management Commands:
  View logs: az container logs --name {self.container_name} --resource-group {self.resource_group}
  Restart: az container restart --name {self.container_name} --resource-group {self.resource_group}
  Stop: az container stop --name {self.container_name} --resource-group {self.resource_group}
  Delete: az container delete --name {self.container_name} --resource-group {self.resource_group}
"""
        return report


def main():
    """Main deployment function"""
    parser = argparse.ArgumentParser(description='Deploy ExponentHR RAG Solution to Azure Container Instances')
    parser.add_argument('--config', required=True, help='Path to deployment configuration file')
    parser.add_argument('--info', action='store_true', help='Show deployment information')
    
    args = parser.parse_args()
    
    # Create deployment manager
    deployment_manager = ACIDeploymentManager(args.config)
    
    if args.info:
        # Show deployment information
        report = deployment_manager.generate_deployment_report()
        print(report)
        return 0
    
    # Run deployment
    success = deployment_manager.deploy()
    
    # Generate and display report
    report = deployment_manager.generate_deployment_report()
    print(report)
    
    # Save report to file
    report_file = f"aci_deployment_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w') as f:
        f.write(report)
    
    print(f"\nDeployment report saved to: {report_file}")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

