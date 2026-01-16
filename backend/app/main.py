import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

                                                                                   
load_dotenv()

from app.core.config import get_settings
from app.core.security import initialize_firebase
from app.api import (
 auth,
 websocket as websocket_routes,
 org,
 me,
 teams,
 extension as extension_routes,
 meeting as meeting_routes,
 meetings as meetings_routes,
 slack as slack_routes,
 tasks as tasks_routes,
 zoom as zoom_routes,
 zoom_sdk as zoom_sdk_routes,
 zoom_webhook as zoom_webhook_routes,
 zoom_ai as zoom_ai_routes,
)

                   
logging.basicConfig(
 level=logging.INFO,
 format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
	"""FastAPI lifespan event handler for startup/shutdown."""
          
	initialize_firebase()
	logger.info('[OK] Firebase Admin SDK initialized')
	print('[OK] Firebase Admin SDK initialized')
	yield
                               
	logger.info('[OK] Application shutting down')
	print('[OK] Shutting down')


app = FastAPI(
 title='Google Meet Intelligence Platform',
 description='AI-powered meeting insights and task management API',
 version='1.0.0',
 lifespan=lifespan,
)

                          
                           
                     
                  
                                             
                                                       
                          
                       
                       
   
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


                 
app.include_router(auth.router)
app.include_router(org.router)
app.include_router(teams.router)
app.include_router(me.router)
app.include_router(websocket_routes.router)
app.include_router(extension_routes.router)
app.include_router(meeting_routes.router)
app.include_router(meetings_routes.router)
app.include_router(tasks_routes.router)
app.include_router(slack_routes.router)
app.include_router(zoom_routes.router)
app.include_router(zoom_sdk_routes.router)
app.include_router(zoom_webhook_routes.router)
app.include_router(zoom_ai_routes.router)


@app.get('/health')
async def health_check():
	"""Health check endpoint."""
	return {'status': 'healthy'}


@app.get('/')
async def root():
	"""Root endpoint."""
	return {
	 'message': 'Google Meet Intelligence Platform API',
	 'docs': '/docs',
	 'health': '/health',
	}


if __name__ == '__main__':
	import uvicorn
	uvicorn.run(
	 'app.main:app',
	 host=os.getenv('API_HOST', '0.0.0.0'),
	 port=int(os.getenv('API_PORT', '9000')),
	 reload=True,
	)