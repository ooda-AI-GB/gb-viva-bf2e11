import os
import random
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
import bcrypt

from database import engine, Base, get_db, User, Request as MaintenanceRequest

# Initialize App
app = FastAPI(title="Building Maintenance Request System")

# Mount Static Files (Ensure directory exists)
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# Session Middleware (for simple auth)
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")

# --- Helper Functions ---

def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()

def require_role(role: str):
    def dependency(request: Request, user: User = Depends(get_current_user)):
        if not user or user.role != role:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return dependency

# --- Startup & Seeding ---

@app.on_event("startup")
def startup_event():
    # Create Tables
    Base.metadata.create_all(bind=engine)
    
    # Seed Data
    db = next(get_db())
    if not db.query(User).first():
        print("Seeding database...")
        
        # 1. Create Users
        users_data = [
            ("tenant", "password", "tenant"),
            ("worker", "password", "worker"),
            ("manager", "password", "manager")
        ]
        
        users = {}
        for username, password, role in users_data:
            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            user = User(username=username, password_hash=hashed.decode('utf-8'), role=role)
            db.add(user)
            db.commit()
            db.refresh(user)
            users[role] = user
            
        # 2. Create Requests
        categories = ["Plumbing", "Electrical", "HVAC", "General"]
        urgencies = ["Low", "Medium", "High", "Emergency"]
        statuses = ["Pending", "In Progress", "Completed"]
        units = [f"10{i}" for i in range(1, 9)] # 8 units: 101-108
        
        for _ in range(12):
            created_at = datetime.utcnow() - timedelta(days=random.randint(0, 30))
            status_val = random.choice(statuses)
            resolved_at = None
            if status_val == "Completed":
                resolved_at = created_at + timedelta(hours=random.randint(1, 48))
            
            req = MaintenanceRequest(
                tenant_id=users["tenant"].id,
                unit_number=random.choice(units),
                category=random.choice(categories),
                urgency=random.choice(urgencies),
                description=f"Issue with {random.choice(['sink', 'light', 'ac', 'door'])} in unit.",
                status=status_val,
                created_at=created_at,
                resolved_at=resolved_at,
                assigned_worker_id=users["worker"].id if status_val != "Pending" else None
            )
            db.add(req)
        
        db.commit()
        print("Database seeded!")
    db.close()

# --- Routes ---

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def index(request: Request, user: Optional[User] = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    
    if user.role == "tenant":
        return RedirectResponse(url="/tenant/requests")
    elif user.role == "worker":
        return RedirectResponse(url="/worker/queue")
    elif user.role == "manager":
        return RedirectResponse(url="/manager/dashboard")
    
    return RedirectResponse(url="/logout")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "title": "Login"})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials", "title": "Login"})
    
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

# --- Tenant Routes ---

@app.get("/tenant/submit", response_class=HTMLResponse)
def submit_request_page(request: Request, user: User = Depends(get_current_user)):
    if not user or user.role != "tenant": return RedirectResponse("/")
    return templates.TemplateResponse("submit_request.html", {"request": request, "user": user, "active_page": "submit", "title": "New Request"})

@app.post("/tenant/submit")
def submit_request(
    request: Request,
    unit_number: str = Form(...),
    category: str = Form(...),
    urgency: str = Form(...),
    description: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user or user.role != "tenant": return RedirectResponse("/")
    
    new_req = MaintenanceRequest(
        tenant_id=user.id,
        unit_number=unit_number,
        category=category,
        urgency=urgency,
        description=description,
        status="Pending"
    )
    db.add(new_req)
    db.commit()
    
    return templates.TemplateResponse("submit_request.html", {
        "request": request, 
        "user": user, 
        "active_page": "submit", 
        "success": True,
        "title": "New Request"
    })

@app.get("/tenant/requests", response_class=HTMLResponse)
def my_requests(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user or user.role != "tenant": return RedirectResponse("/")
    
    requests = db.query(MaintenanceRequest).filter(MaintenanceRequest.tenant_id == user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    return templates.TemplateResponse("my_requests.html", {
        "request": request, 
        "user": user, 
        "requests": requests, 
        "active_page": "requests",
        "title": "My Requests"
    })

# --- Worker Routes ---

@app.get("/worker/queue", response_class=HTMLResponse)
def work_queue(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user or user.role != "worker": return RedirectResponse("/")
    
    # Sort by urgency (Emergency > High > Medium > Low) and then status
    # In a real app, we'd use a custom sort or enum order. Here we do it in python or simple order.
    requests = db.query(MaintenanceRequest).filter(MaintenanceRequest.status != "Completed").all()
    
    # Custom sort for urgency
    urgency_order = {"Emergency": 0, "High": 1, "Medium": 2, "Low": 3}
    requests.sort(key=lambda x: urgency_order.get(x.urgency, 4))
    
    return templates.TemplateResponse("work_queue.html", {
        "request": request, 
        "user": user, 
        "requests": requests, 
        "active_page": "queue",
        "title": "Work Queue"
    })

@app.post("/worker/update/{req_id}")
def update_request(
    req_id: int, 
    request: Request,
    status: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user or user.role != "worker": return RedirectResponse("/")
    
    req = db.query(MaintenanceRequest).filter(MaintenanceRequest.id == req_id).first()
    if req:
        req.status = status
        req.assigned_worker_id = user.id
        if status == "Completed":
            req.resolved_at = datetime.utcnow()
        db.commit()
        
    return RedirectResponse(url="/worker/queue", status_code=303)

# --- Manager Routes ---

@app.get("/manager/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user or user.role != "manager": return RedirectResponse("/")
    
    all_requests = db.query(MaintenanceRequest).all()
    
    open_requests = len([r for r in all_requests if r.status != "Completed"])
    completed_requests = [r for r in all_requests if r.status == "Completed"]
    completed_count = len(completed_requests)
    emergency_count = len([r for r in all_requests if r.urgency == "Emergency" and r.status != "Completed"])
    
    # Calculate avg resolution time
    total_time = 0
    count_time = 0
    for r in completed_requests:
        if r.resolved_at and r.created_at:
            delta = (r.resolved_at - r.created_at).total_seconds() / 3600 # hours
            total_time += delta
            count_time += 1
            
    avg_resolution_time = round(total_time / count_time, 1) if count_time > 0 else 0
    
    recent_requests = db.query(MaintenanceRequest).order_by(MaintenanceRequest.created_at.desc()).limit(10).all()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user": user, 
        "active_page": "dashboard",
        "open_requests": open_requests,
        "avg_resolution_time": avg_resolution_time,
        "emergency_count": emergency_count,
        "completed_count": completed_count,
        "recent_requests": recent_requests,
        "title": "Manager Dashboard"
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
