import os
import sys
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
# Add parent directory to path for RAG components
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from flask import Flask, send_from_directory, request, jsonify
from flask_cors import CORS
from src.models.user import db
from src.routes.user import user_bp

# Import RAG system components
try:
    from rag_orchestrator import RAGOrchestrator
    from azure_search_integration import AzureSearchIntegration
    from synchronization_service import SynchronizationService
    from change_detection import ChangeDetectionSystem
except ImportError as e:
    print(f"Warning: Could not import RAG components: {e}")
    print("Make sure the RAG system files are in the parent directory")

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))
app.config['SECRET_KEY'] = 'exponenthr-rag-secret-key-change-in-production'

# Enable CORS for all routes
CORS(app)

# Register existing blueprints
app.register_blueprint(user_bp, url_prefix='/api')

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'database', 'app.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# RAG system configuration
RAG_CONFIG = {
    'azure_storage_account_url': os.getenv('AZURE_STORAGE_ACCOUNT_URL'),
    'azure_search_endpoint': os.getenv('AZURE_SEARCH_ENDPOINT'),
    'azure_search_key': os.getenv('AZURE_SEARCH_KEY'),
    'search_index_name': os.getenv('AZURE_SEARCH_INDEX_NAME', 'exponenthr-docs'),
    'openai_api_key': os.getenv('OPENAI_API_KEY'),
    'content_container': os.getenv('CONTENT_CONTAINER', 'scraped-content'),
    'request_delay': float(os.getenv('REQUEST_DELAY', '1.0')),
    'sync_batch_size': int(os.getenv('SYNC_BATCH_SIZE', '20')),
    'search_top_k': int(os.getenv('SEARCH_TOP_K', '10')),
    'embedding_model': os.getenv('EMBEDDING_MODEL', 'text-embedding-ada-002'),
    'embedding_dimension': int(os.getenv('EMBEDDING_DIMENSION', '1536'))
}

# Global RAG system instances
rag_orchestrator = None
search_integration = None
sync_service = None

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def initialize_rag_system():
    """Initialize the RAG system components"""
    global rag_orchestrator, search_integration, sync_service
    
    try:
        logger.info("Initializing RAG system components...")
        
        # Initialize search integration
        search_integration = AzureSearchIntegration(RAG_CONFIG)
        search_integration.initialize_clients()
        
        # Initialize orchestrator
        rag_orchestrator = RAGOrchestrator(RAG_CONFIG)
        await rag_orchestrator.initialize()
        
        # Initialize synchronization service
        sync_service = SynchronizationService(RAG_CONFIG)
        await sync_service.initialize()
        
        logger.info("RAG system initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize RAG system: {str(e)}")
        raise


def run_async(coro):
    """Helper function to run async functions in Flask routes"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)


# RAG API Routes

@app.route('/api/search', methods=['POST'])
def search_documents():
    """Search documents in the knowledge base"""
    try:
        data = request.get_json()
        query = data.get('query', '')
        filters = data.get('filters', {})
        search_type = data.get('search_type', 'hybrid')
        
        if not query:
            return jsonify({'error': 'Query is required'}), 400
        
        if not search_integration:
            return jsonify({'error': 'Search service not initialized'}), 503
        
        # Perform search
        results = run_async(search_integration.search_documents(query, filters, search_type))
        
        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append({
                'id': result.document_id,
                'url': result.url,
                'title': result.title,
                'snippet': result.content_snippet,
                'score': result.score,
                'highlights': result.highlights,
                'metadata': result.metadata
            })
        
        return jsonify({
            'query': query,
            'results': formatted_results,
            'total_results': len(formatted_results),
            'search_type': search_type
        })
        
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/suggest', methods=['GET'])
def get_suggestions():
    """Get query suggestions"""
    try:
        partial_query = request.args.get('q', '')
        top = int(request.args.get('top', 5))
        
        if not partial_query:
            return jsonify({'suggestions': []})
        
        if not search_integration:
            return jsonify({'error': 'Search service not initialized'}), 503
        
        suggestions = run_async(search_integration.suggest_queries(partial_query, top))
        
        return jsonify({'suggestions': suggestions})
        
    except Exception as e:
        logger.error(f"Suggestions error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sync/full', methods=['POST'])
def trigger_full_sync():
    """Trigger a full synchronization"""
    try:
        data = request.get_json() or {}
        view_types = data.get('view_types', ['personal', 'management'])
        
        if not sync_service:
            return jsonify({'error': 'Sync service not initialized'}), 503
        
        # Start synchronization in background
        result = run_async(sync_service.perform_full_synchronization(view_types))
        
        return jsonify({
            'operation_id': result.operation_id,
            'success': result.success,
            'total_processed': result.total_processed,
            'newly_indexed': result.newly_indexed,
            'updated_indexed': result.updated_indexed,
            'removed_indexed': result.removed_indexed,
            'errors': result.errors,
            'execution_time': result.execution_time
        })
        
    except Exception as e:
        logger.error(f"Full sync error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sync/incremental', methods=['POST'])
def trigger_incremental_sync():
    """Trigger an incremental synchronization"""
    try:
        if not sync_service:
            return jsonify({'error': 'Sync service not initialized'}), 503
        
        result = run_async(sync_service.perform_incremental_synchronization())
        
        return jsonify({
            'operation_id': result.operation_id,
            'success': result.success,
            'total_processed': result.total_processed,
            'updated_indexed': result.updated_indexed,
            'errors': result.errors,
            'execution_time': result.execution_time
        })
        
    except Exception as e:
        logger.error(f"Incremental sync error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sync/status', methods=['GET'])
def get_sync_status():
    """Get synchronization status"""
    try:
        if not sync_service:
            return jsonify({'error': 'Sync service not initialized'}), 503
        
        # Get active operations
        active_operations = sync_service.get_all_active_operations()
        
        # Get recent sync history
        recent_syncs = sync_service.get_sync_history(10)
        
        # Get sync statistics
        stats = sync_service._get_sync_statistics()
        
        return jsonify({
            'active_operations': [
                {
                    'operation_id': op.operation_id,
                    'operation_type': op.operation_type,
                    'status': op.status,
                    'started_at': op.started_at,
                    'urls_processed': op.urls_processed,
                    'urls_updated': op.urls_updated,
                    'urls_failed': op.urls_failed
                }
                for op in active_operations
            ],
            'recent_syncs': [
                {
                    'operation_id': sync.operation_id,
                    'success': sync.success,
                    'total_processed': sync.total_processed,
                    'execution_time': sync.execution_time
                }
                for sync in recent_syncs
            ],
            'statistics': stats
        })
        
    except Exception as e:
        logger.error(f"Sync status error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/system/status', methods=['GET'])
def get_system_status():
    """Get overall system status"""
    try:
        status = {
            'timestamp': datetime.now().isoformat(),
            'services': {
                'search_integration': search_integration is not None,
                'rag_orchestrator': rag_orchestrator is not None,
                'sync_service': sync_service is not None
            },
            'configuration': {
                'search_index_name': RAG_CONFIG.get('search_index_name'),
                'embedding_model': RAG_CONFIG.get('embedding_model'),
                'search_top_k': RAG_CONFIG.get('search_top_k')
            }
        }
        
        # Get search index statistics if available
        if search_integration:
            try:
                index_stats = search_integration.get_index_statistics()
                status['index_statistics'] = index_stats
            except:
                status['index_statistics'] = {'error': 'Could not retrieve index statistics'}
        
        # Get orchestrator status if available
        if rag_orchestrator:
            try:
                orchestrator_status = rag_orchestrator.get_system_status()
                status['orchestrator_status'] = {
                    'last_full_scan': orchestrator_status.last_full_scan,
                    'last_incremental_scan': orchestrator_status.last_incremental_scan,
                    'total_documents': orchestrator_status.total_documents,
                    'monitored_urls': orchestrator_status.monitored_urls,
                    'system_health': orchestrator_status.system_health,
                    'error_rate': orchestrator_status.error_rate
                }
            except:
                status['orchestrator_status'] = {'error': 'Could not retrieve orchestrator status'}
        
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"System status error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'services': {
                'api': True,
                'search': search_integration is not None,
                'orchestrator': rag_orchestrator is not None,
                'sync': sync_service is not None
            }
        }
        
        # Check if all critical services are available
        all_healthy = all(health_status['services'].values())
        
        if not all_healthy:
            health_status['status'] = 'degraded'
            return jsonify(health_status), 503
        
        return jsonify(health_status)
        
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


# Static file serving
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    static_folder_path = app.static_folder
    if static_folder_path is None:
        return "Static folder not configured", 404

    if path != "" and os.path.exists(os.path.join(static_folder_path, path)):
        return send_from_directory(static_folder_path, path)
    else:
        index_path = os.path.join(static_folder_path, 'index.html')
        if os.path.exists(index_path):
            return send_from_directory(static_folder_path, 'index.html')
        else:
            return "index.html not found", 404


# Initialize database and RAG system
with app.app_context():
    db.create_all()
    
    # Initialize RAG system if configuration is available
    if RAG_CONFIG.get('azure_search_endpoint') and RAG_CONFIG.get('openai_api_key'):
        try:
            run_async(initialize_rag_system())
            logger.info("RAG system initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize RAG system: {str(e)}")
            logger.warning("API will run in limited mode without RAG functionality")
    else:
        logger.warning("RAG system configuration incomplete. Running in limited mode.")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
