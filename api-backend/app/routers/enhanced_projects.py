from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
import json
from datetime import datetime
from typing import List, Optional

from app.models.projects import Project, ProjectTool
from app.models.users import User
from app.services.database import get_async_session
from app.routers.conversations import decode_email_from_token, get_user_id_from_email

router = APIRouter()

# Enhanced project response models
class ProjectContextUpdate(BaseModel):
    context: Optional[str] = None
    goals: Optional[str] = None
    decisions: Optional[str] = None
    preferences: Optional[str] = None

class ProjectToolConfig(BaseModel):
    tool_name: str
    tool_config: Optional[str] = None
    is_enabled: bool = True

class EnhancedProjectResponse(BaseModel):
    project_id: str
    name: str
    description: Optional[str]
    context: Optional[str]
    goals: Optional[str]
    decisions: Optional[str]
    preferences: Optional[str]
    tools: List[ProjectToolConfig]
    created_at: datetime
    updated_at: Optional[datetime]

@router.get("/projects/{project_id}/context")
async def get_project_context(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_async_session)
):
    """Get project context, goals, decisions, and preferences"""
    try:
        # Authentication
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
        
        token = auth_header.split(" ")[1]
        email = decode_email_from_token(token)
        user_id = await get_user_id_from_email(email)

        # Get project with tools
        result = await db.execute(
            select(Project)
            .where(Project.project_id == project_id)
            .where(Project.user_id == user_id)
            .options(selectinload(Project.tools))
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Format tools
        tools = []
        for tool in project.tools:
            tools.append(ProjectToolConfig(
                tool_name=tool.tool_name,
                tool_config=tool.tool_config,
                is_enabled=tool.is_enabled == "true"
            ))
        
        return EnhancedProjectResponse(
            project_id=str(project.project_id),
            name=project.name,
            description=project.description,
            context=project.context,
            goals=project.goals,
            decisions=project.decisions,
            preferences=project.preferences,
            tools=tools,
            created_at=project.created_at,
            updated_at=project.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.put("/projects/{project_id}/context")
async def update_project_context(
    request: Request,
    project_id: str,
    context_update: ProjectContextUpdate,
    db: AsyncSession = Depends(get_async_session)
):
    """Update project context, goals, decisions, and preferences"""
    try:
        # Authentication
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
        
        token = auth_header.split(" ")[1]
        email = decode_email_from_token(token)
        user_id = await get_user_id_from_email(email)

        # Get project
        result = await db.execute(
            select(Project)
            .where(Project.project_id == project_id)
            .where(Project.user_id == user_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Update fields
        update_data = {"updated_at": datetime.utcnow()}
        if context_update.context is not None:
            update_data["context"] = context_update.context
        if context_update.goals is not None:
            update_data["goals"] = context_update.goals
        if context_update.decisions is not None:
            update_data["decisions"] = context_update.decisions
        if context_update.preferences is not None:
            update_data["preferences"] = context_update.preferences
        
        await db.execute(
            update(Project)
            .where(Project.project_id == project_id)
            .values(**update_data)
        )
        await db.commit()
        
        return {"message": "Project context updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/projects/{project_id}/tools")
async def configure_project_tool(
    request: Request,
    project_id: str,
    tool_config: ProjectToolConfig,
    db: AsyncSession = Depends(get_async_session)
):
    """Configure a tool for a project"""
    try:
        # Authentication
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
        
        token = auth_header.split(" ")[1]
        email = decode_email_from_token(token)
        user_id = await get_user_id_from_email(email)

        # Verify project ownership
        result = await db.execute(
            select(Project)
            .where(Project.project_id == project_id)
            .where(Project.user_id == user_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Check if tool already exists
        existing_tool = await db.execute(
            select(ProjectTool)
            .where(ProjectTool.project_id == project_id)
            .where(ProjectTool.tool_name == tool_config.tool_name)
        )
        tool = existing_tool.scalar_one_or_none()
        
        if tool:
            # Update existing tool
            await db.execute(
                update(ProjectTool)
                .where(ProjectTool.tool_id == tool.tool_id)
                .values(
                    tool_config=tool_config.tool_config,
                    is_enabled="true" if tool_config.is_enabled else "false",
                    updated_at=datetime.utcnow()
                )
            )
        else:
            # Create new tool
            new_tool = ProjectTool(
                project_id=project_id,
                tool_name=tool_config.tool_name,
                tool_config=tool_config.tool_config,
                is_enabled="true" if tool_config.is_enabled else "false"
            )
            db.add(new_tool)
        
        await db.commit()
        return {"message": f"Tool {tool_config.tool_name} configured successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/projects/{project_id}/tools")
async def get_project_tools(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_async_session)
):
    """Get all tools configured for a project"""
    try:
        # Authentication
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
        
        token = auth_header.split(" ")[1]
        email = decode_email_from_token(token)
        user_id = await get_user_id_from_email(email)

        # Verify project ownership
        result = await db.execute(
            select(Project)
            .where(Project.project_id == project_id)
            .where(Project.user_id == user_id)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get tools
        tools_result = await db.execute(
            select(ProjectTool)
            .where(ProjectTool.project_id == project_id)
        )
        tools = tools_result.scalars().all()
        
        return [
            ProjectToolConfig(
                tool_name=tool.tool_name,
                tool_config=tool.tool_config,
                is_enabled=tool.is_enabled == "true"
            )
            for tool in tools
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
