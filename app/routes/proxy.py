from fastapi import APIRouter, HTTPException, Request, Header
from app.database import supabase_client
import httpx

router = APIRouter(tags=["Proxy Engine"])

@router.post("/v1/route/{route_id}")
async def proxy_webhook(
    route_id: str, 
    request: Request,
    user_agent: str = Header(None)
):
    # 1. Light Anti-Spam Check: Trap simple headless bots missing User-Agents
    if not user_agent or "python-requests" in user_agent.lower():
        raise HTTPException(status_code=403, detail="Automated requests blocked.")

    # 2. Extract incoming form or JSON data
    try:
        incoming_data = await request.json()
    except Exception:
        # Fallback to form data if it's a standard static web contact form
        form_data = await request.form()
        incoming_data = dict(form_data)

    # 3. Simple Honeypot Check: Catch automated form spammers
    # Bots fill out every field. If they fill out 'honeypot_field', drop them silently.
    if incoming_data.get("honeypot_field") or incoming_data.get("_gotcha"):
        return {"status": "success", "message": "Filtered"} 

    # 4. Lookup the hidden destination URL in Supabase
    db_query = supabase_client.table("routes").select("*").eq("id", route_id).eq("is_active", True).execute()
    
    if not db_query.data:
        raise HTTPException(status_code=404, detail="Active routing link not found.")
    
    route_record = db_query.data[0]
    destination = route_record["destination_url"]

    # 5. Clean & Forward the data asynchronously (Doesn't block server threads)
    # Strip away the honeypot key before forwarding to clean up client's CRM/Zapier tasks
    incoming_data.pop("honeypot_field", None)
    incoming_data.pop("_gotcha", None)

    async with httpx.AsyncClient() as client:
        try:
            # Forward data securely, hiding the true destination from the public frontend
            response = await client.post(destination, json=incoming_data, timeout=5.0)
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="Destination server unreachable.")

    # 6. Increment request count on the free-tier database tracker
    supabase_client.table("routes").update(
        {"requests_count": route_record["requests_count"] + 1}
    ).eq("id", route_id).execute()

    return {
        "status": "forwarded", 
        "destination_status": response.status_code
    }
