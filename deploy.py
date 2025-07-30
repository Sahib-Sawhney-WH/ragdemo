#!/usr/bin/env python3
"""
Deployment Script for ExponentHR RAG Scraping Solution
Automates the deployment and configuration of all system components.
"""

import asyncio
import json
import logging
import os
import sys
import argparse
from typing import Dict, List, Optional
from datetime import datetime
import subprocess
import time

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.search.documents.indexes import SearchIndexClient
from azure.keyvault.secrets import SecretClient


class RAGDeploymentManager:
    """
    Deployment manager for the ExponentHR RAG scraping solution.
    Handles Azure resource creation, configuration, and system initialization.
    """
    
    def __init__(self, config_file: str):
        """
        Initialize the deployment manager.
        
        Args:
            config_file: Path to deployment configuration file
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.logger = self._setup_logging()
        
        # Azure clients
        self.credential = DefaultAzureCredential()
        self.blob_client = None
        self.search_client = None
        self.keyvault_client = None
        
        # Deployment state
        self.deployment_status = {
            'started_at': None,
            'completed_at': None,
            'status': 'pending',
            'steps_completed': [],
            'errors': []
        }
    
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
        logger = logging.getLogger('RAGDeploymentManager')
        logger.setLevel(logging.INFO)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # File handler
        log_file = f"deployment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(console_formatter)
        logger.addHandler(file_handler)
        
        return logger
    
    async def deploy(self) -> bool:
        """
        Execute the complete deployment process.
        
        Returns:
            True if deployment successful, False otherwise
        """
        self.deployment_status['started_at'] = datetime.now().isoformat()
        self.deployment_status['status'] = 'running'
        
        self.logger.info("Starting ExponentHR RAG solution deployment")
        
        try:
            # Step 1: Validate prerequisites
            await self._validate_prerequisites()
            self.deployment_status['steps_completed'].append('prerequisites_validated')
            
            # Step 2: Initialize Azure clients
            await self._initialize_azure_clients()
            self.deployment_status['steps_completed'].append('azure_clients_initialized')
            
            # Step 3: Create Azure resources
            await self._create_azure_resources()
            self.deployment_status['steps_completed'].append('azure_resources_created')
            
            # Step 4: Configure storage containers
            await self._configure_storage_containers()
            self.deployment_status['steps_completed'].append('storage_configured')
            
            # Step 5: Create search index
            await self._create_search_index()
            self.deployment_status['steps_completed'].append('search_index_created')
            
            # Step 6: Install Python dependencies
            await self._install_dependencies()
            self.deployment_status['steps_completed'].append('dependencies_installed')
            
            # Step 7: Configure secrets and environment
            await self._configure_secrets()
            self.deployment_status['steps_completed'].append('secrets_configured')
            
            # Step 8: Initialize system components
            await self._initialize_system_components()
            self.deployment_status['steps_completed'].append('system_initialized')
            
            # Step 9: Run initial data load
            if self.config.get('run_initial_load', True):
                await self._run_initial_data_load()
                self.deployment_status['steps_completed'].append('initial_data_loaded')
            
            # Step 10: Configure monitoring and alerts
            await self._configure_monitoring()
            self.deployment_status['steps_completed'].append('monitoring_configured')
            
            self.deployment_status['status'] = 'completed'
            self.deployment_status['completed_at'] = datetime.now().isoformat()
            
            self.logger.info("Deployment completed successfully")
            return True
            
        except Exception as e:
            error_msg = f"Deployment failed: {str(e)}"
            self.logger.error(error_msg)
            self.deployment_status['errors'].append(error_msg)
            self.deployment_status['status'] = 'failed'
            self.deployment_status['completed_at'] = datetime.now().isoformat()
            return False
    
    async def _validate_prerequisites(self) -> None:
        """Validate deployment prerequisites"""
        self.logger.info("Validating prerequisites...")
        
        # Check Python version
        if sys.version_info < (3, 8):
            raise Exception("Python 3.8 or higher is required")
        
        # Check required configuration
        required_config = [
            'azure_subscription_id',
            'azure_resource_group',
            'azure_storage_account_name',
            'azure_search_service_name',
            'azure_region'
        ]
        
        for key in required_config:
            if key not in self.config:
                raise Exception(f"Missing required configuration: {key}")
        
        # Check Azure CLI availability
        try:
            result = subprocess.run(['az', '--version'], capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception("Azure CLI not found or not working")
        except FileNotFoundError:
            raise Exception("Azure CLI is not installed")
        
        # Check if logged into Azure
        try:
            result = subprocess.run(['az', 'account', 'show'], capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception("Not logged into Azure CLI. Run 'az login' first.")
        except Exception:
            raise Exception("Azure CLI authentication check failed")
        
        self.logger.info("Prerequisites validated successfully")
    
    async def _initialize_azure_clients(self) -> None:
        """Initialize Azure service clients"""
        self.logger.info("Initializing Azure clients...")
        
        try:
            # Initialize Blob Storage client
            storage_account_url = f"https://{self.config['azure_storage_account_name']}.blob.core.windows.net"
            self.blob_client = BlobServiceClient(
                account_url=storage_account_url,
                credential=self.credential
            )
            
            # Initialize Search client
            search_endpoint = f"https://{self.config['azure_search_service_name']}.search.windows.net"
            self.search_client = SearchIndexClient(
                endpoint=search_endpoint,
                credential=self.credential
            )
            
            # Initialize Key Vault client if configured
            if self.config.get('azure_keyvault_name'):
                keyvault_url = f"https://{self.config['azure_keyvault_name']}.vault.azure.net"
                self.keyvault_client = SecretClient(
                    vault_url=keyvault_url,
                    credential=self.credential
                )
            
            self.logger.info("Azure clients initialized successfully")
            
        except Exception as e:
            raise Exception(f"Failed to initialize Azure clients: {str(e)}")
    
    async def _create_azure_resources(self) -> None:
        """Create required Azure resources"""
        self.logger.info("Creating Azure resources...")
        
        subscription_id = self.config['azure_subscription_id']
        resource_group = self.config['azure_resource_group']
        region = self.config['azure_region']
        
        try:
            # Create resource group if it doesn't exist
            self.logger.info(f"Creating resource group: {resource_group}")
            cmd = [
                'az', 'group', 'create',
                '--name', resource_group,
                '--location', region,
                '--subscription', subscription_id
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.warning(f"Resource group creation warning: {result.stderr}")
            
            # Create storage account
            storage_account = self.config['azure_storage_account_name']
            self.logger.info(f"Creating storage account: {storage_account}")
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
                raise Exception(f"Failed to create storage account: {result.stderr}")
            
            # Create search service
            search_service = self.config['azure_search_service_name']
            search_sku = self.config.get('azure_search_sku', 'basic')
            self.logger.info(f"Creating search service: {search_service}")
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
                raise Exception(f"Failed to create search service: {result.stderr}")
            
            # Create Key Vault if configured
            if self.config.get('azure_keyvault_name'):
                keyvault_name = self.config['azure_keyvault_name']
                self.logger.info(f"Creating Key Vault: {keyvault_name}")
                cmd = [
                    'az', 'keyvault', 'create',
                    '--name', keyvault_name,
                    '--resource-group', resource_group,
                    '--location', region,
                    '--subscription', subscription_id
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0 and "already exists" not in result.stderr:
                    raise Exception(f"Failed to create Key Vault: {result.stderr}")
            
            self.logger.info("Azure resources created successfully")
            
        except Exception as e:
            raise Exception(f"Failed to create Azure resources: {str(e)}")
    
    async def _configure_storage_containers(self) -> None:
        """Configure required storage containers"""
        self.logger.info("Configuring storage containers...")
        
        try:
            containers = [
                'scraped-content',
                'system-state',
                'change-detection',
                'logs'
            ]
            
            for container_name in containers:
                try:
                    container_client = self.blob_client.get_container_client(container_name)
                    container_client.create_container()
                    self.logger.info(f"Created container: {container_name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        self.logger.info(f"Container already exists: {container_name}")
                    else:
                        raise
            
            self.logger.info("Storage containers configured successfully")
            
        except Exception as e:
            raise Exception(f"Failed to configure storage containers: {str(e)}")
    
    async def _create_search_index(self) -> None:
        """Create the search index"""
        self.logger.info("Creating search index...")
        
        try:
            # Import the search integration module
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            from azure_search_integration import AzureSearchIntegration
            
            # Create search integration instance
            search_config = {
                'azure_search_endpoint': f"https://{self.config['azure_search_service_name']}.search.windows.net",
                'search_index_name': self.config.get('search_index_name', 'exponenthr-docs'),
                'embedding_model': self.config.get('embedding_model', 'text-embedding-ada-002'),
                'embedding_dimension': self.config.get('embedding_dimension', 1536)
            }
            
            search_integration = AzureSearchIntegration(search_config)
            search_integration.initialize_clients()
            
            # Create the index
            search_integration.create_search_index()
            
            self.logger.info("Search index created successfully")
            
        except Exception as e:
            raise Exception(f"Failed to create search index: {str(e)}")
    
    async def _install_dependencies(self) -> None:
        """Install Python dependencies"""
        self.logger.info("Installing Python dependencies...")
        
        try:
            # Install from requirements.txt
            requirements_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')
            if os.path.exists(requirements_file):
                cmd = [sys.executable, '-m', 'pip', 'install', '-r', requirements_file]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(f"Failed to install dependencies: {result.stderr}")
            
            # Install Playwright browsers
            cmd = [sys.executable, '-m', 'playwright', 'install', 'chromium']
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.warning(f"Playwright browser installation warning: {result.stderr}")
            
            self.logger.info("Dependencies installed successfully")
            
        except Exception as e:
            raise Exception(f"Failed to install dependencies: {str(e)}")
    
    async def _configure_secrets(self) -> None:
        """Configure secrets and environment variables"""
        self.logger.info("Configuring secrets and environment...")
        
        try:
            # Create environment configuration file
            env_config = {
                'AZURE_STORAGE_ACCOUNT_URL': f"https://{self.config['azure_storage_account_name']}.blob.core.windows.net",
                'AZURE_SEARCH_ENDPOINT': f"https://{self.config['azure_search_service_name']}.search.windows.net",
                'AZURE_SEARCH_INDEX_NAME': self.config.get('search_index_name', 'exponenthr-docs'),
                'AZURE_KEYVAULT_URL': f"https://{self.config['azure_keyvault_name']}.vault.azure.net" if self.config.get('azure_keyvault_name') else '',
                'CONTENT_CONTAINER': 'scraped-content',
                'REQUEST_DELAY': str(self.config.get('request_delay', 1.0)),
                'SYNC_BATCH_SIZE': str(self.config.get('sync_batch_size', 20)),
                'INCREMENTAL_UPDATE_HOURS': str(self.config.get('incremental_update_hours', 6)),
                'FULL_SCAN_DAYS': str(self.config.get('full_scan_days', 7))
            }
            
            # Write environment file
            env_file = os.path.join(os.path.dirname(__file__), '.env')
            with open(env_file, 'w') as f:
                for key, value in env_config.items():
                    f.write(f"{key}={value}\n")
            
            # Store secrets in Key Vault if configured
            if self.keyvault_client and self.config.get('openai_api_key'):
                self.keyvault_client.set_secret('openai-api-key', self.config['openai_api_key'])
                self.logger.info("OpenAI API key stored in Key Vault")
            
            self.logger.info("Secrets and environment configured successfully")
            
        except Exception as e:
            raise Exception(f"Failed to configure secrets: {str(e)}")
    
    async def _initialize_system_components(self) -> None:
        """Initialize system components"""
        self.logger.info("Initializing system components...")
        
        try:
            # Import and initialize the orchestrator
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            from rag_orchestrator import RAGOrchestrator
            
            # Create orchestrator configuration
            orchestrator_config = {
                'azure_storage_account_url': f"https://{self.config['azure_storage_account_name']}.blob.core.windows.net",
                'azure_search_endpoint': f"https://{self.config['azure_search_service_name']}.search.windows.net",
                'search_index_name': self.config.get('search_index_name', 'exponenthr-docs'),
                'openai_api_key': self.config.get('openai_api_key'),
                'content_container': 'scraped-content',
                'request_delay': self.config.get('request_delay', 1.0),
                'incremental_update_hours': self.config.get('incremental_update_hours', 6),
                'full_scan_days': self.config.get('full_scan_days', 7)
            }
            
            # Initialize orchestrator
            orchestrator = RAGOrchestrator(orchestrator_config)
            await orchestrator.initialize()
            
            # Save initial system state
            await orchestrator._save_system_state()
            
            # Shutdown orchestrator
            await orchestrator.shutdown()
            
            self.logger.info("System components initialized successfully")
            
        except Exception as e:
            raise Exception(f"Failed to initialize system components: {str(e)}")
    
    async def _run_initial_data_load(self) -> None:
        """Run initial data load"""
        self.logger.info("Running initial data load...")
        
        try:
            # Import and run the orchestrator
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            from rag_orchestrator import RAGOrchestrator
            
            # Create orchestrator configuration
            orchestrator_config = {
                'azure_storage_account_url': f"https://{self.config['azure_storage_account_name']}.blob.core.windows.net",
                'azure_search_endpoint': f"https://{self.config['azure_search_service_name']}.search.windows.net",
                'search_index_name': self.config.get('search_index_name', 'exponenthr-docs'),
                'openai_api_key': self.config.get('openai_api_key'),
                'content_container': 'scraped-content',
                'request_delay': self.config.get('request_delay', 1.0)
            }
            
            # Initialize and run orchestrator
            orchestrator = RAGOrchestrator(orchestrator_config)
            await orchestrator.initialize()
            
            # Run initial full discovery and scraping (limited for deployment)
            view_types = self.config.get('initial_load_views', ['personal'])
            result = await orchestrator.perform_full_discovery_and_scraping(view_types)
            
            if result.success:
                self.logger.info(f"Initial data load completed: {result.processed_urls} URLs processed")
            else:
                self.logger.warning(f"Initial data load completed with errors: {len(result.errors)} errors")
            
            # Shutdown orchestrator
            await orchestrator.shutdown()
            
            self.logger.info("Initial data load completed")
            
        except Exception as e:
            raise Exception(f"Failed to run initial data load: {str(e)}")
    
    async def _configure_monitoring(self) -> None:
        """Configure monitoring and alerts"""
        self.logger.info("Configuring monitoring...")
        
        try:
            # Create monitoring configuration
            monitoring_config = {
                'log_level': self.config.get('log_level', 'INFO'),
                'metrics_enabled': self.config.get('metrics_enabled', True),
                'alert_email': self.config.get('alert_email'),
                'health_check_interval': self.config.get('health_check_interval', 300)
            }
            
            # Write monitoring configuration
            monitoring_file = os.path.join(os.path.dirname(__file__), 'monitoring_config.json')
            with open(monitoring_file, 'w') as f:
                json.dump(monitoring_config, f, indent=2)
            
            self.logger.info("Monitoring configured successfully")
            
        except Exception as e:
            raise Exception(f"Failed to configure monitoring: {str(e)}")
    
    def get_deployment_status(self) -> Dict:
        """Get current deployment status"""
        return self.deployment_status.copy()
    
    def generate_deployment_report(self) -> str:
        """Generate deployment report"""
        report = f"""
ExponentHR RAG Solution Deployment Report
========================================

Deployment Status: {self.deployment_status['status']}
Started: {self.deployment_status['started_at']}
Completed: {self.deployment_status['completed_at']}

Steps Completed:
{chr(10).join(f"  ✓ {step}" for step in self.deployment_status['steps_completed'])}

Configuration:
  Resource Group: {self.config['azure_resource_group']}
  Storage Account: {self.config['azure_storage_account_name']}
  Search Service: {self.config['azure_search_service_name']}
  Region: {self.config['azure_region']}
  Search Index: {self.config.get('search_index_name', 'exponenthr-docs')}

Errors:
{chr(10).join(f"  ✗ {error}" for error in self.deployment_status['errors']) if self.deployment_status['errors'] else "  None"}

Next Steps:
1. Verify all Azure resources are created and accessible
2. Test the search functionality
3. Configure scheduled synchronization
4. Set up monitoring and alerts
5. Review and adjust configuration as needed
"""
        return report


async def main():
    """Main deployment function"""
    parser = argparse.ArgumentParser(description='Deploy ExponentHR RAG Solution')
    parser.add_argument('--config', required=True, help='Path to deployment configuration file')
    parser.add_argument('--validate-only', action='store_true', help='Only validate prerequisites')
    
    args = parser.parse_args()
    
    # Create deployment manager
    deployment_manager = RAGDeploymentManager(args.config)
    
    if args.validate_only:
        try:
            await deployment_manager._validate_prerequisites()
            print("✓ Prerequisites validation passed")
            return 0
        except Exception as e:
            print(f"✗ Prerequisites validation failed: {str(e)}")
            return 1
    
    # Run full deployment
    success = await deployment_manager.deploy()
    
    # Generate and display report
    report = deployment_manager.generate_deployment_report()
    print(report)
    
    # Save report to file
    report_file = f"deployment_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w') as f:
        f.write(report)
    
    print(f"\nDeployment report saved to: {report_file}")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())

