"""Shared guarded inventory write used by local and reviewed integration inputs."""
from fastapi import HTTPException
from sqlalchemy import select
from .models import InventoryLot, StockMovement
from .entities import guard, bump_version, entity_risk
from .policies import enforce
from .audit import append_audit


def apply_movement(db,user,body):
    lot=db.scalar(select(InventoryLot).where(InventoryLot.id==body.lot_id).with_for_update())
    if lot is None: raise HTTPException(404,"Inventory lot not found")
    guard(db,user,"inventory",lot.id,True)
    if lot.status=="quarantined" and body.movement_type!="transfer": raise HTTPException(409,"Quarantined lots cannot move")
    delta=body.quantity if body.movement_type in ("receipt","adjustment") else -body.quantity
    if lot.quantity+delta<0: raise HTTPException(422,"Movement would make stock negative")
    enforce(db,user,"inventory.change",risk=entity_risk(db,"inventory",lot.id),quantity_delta=delta)
    lot.quantity+=delta;bump_version(db,"inventory",lot.id)
    item=StockMovement(lot_id=lot.id,movement_type=body.movement_type,quantity=body.quantity,reason=body.reason,created_by=user.id)
    db.add(item);db.flush()
    append_audit(db,"inventory.movement_created",user.id,{"id":item.id,"lot_id":lot.id})
    return item
