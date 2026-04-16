import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, ForeignKey,
    DateTime, Text,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

def _uuid():
    return str(uuid.uuid4())

# ── Domain 1: Source (FMECA) ──────────────────────────────────────────────────

class FunctionalLocation(Base):
    __tablename__ = "functional_location"

    id = Column(String, primary_key=True, default=_uuid)
    parent_id = Column(String, ForeignKey("functional_location.id"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    level = Column(Integer)           # 1=Train, 2=System, 3=Sub-system, 4=Equipment
    asset_class = Column(String)
    is_safety_critical = Column(Boolean, default=False)
    dataset_id = Column(String)

    children = relationship(
        "FunctionalLocation",
        primaryjoin="FunctionalLocation.parent_id == FunctionalLocation.id",
        foreign_keys="FunctionalLocation.parent_id",
        back_populates="parent",
    )
    parent = relationship(
        "FunctionalLocation",
        primaryjoin="FunctionalLocation.parent_id == FunctionalLocation.id",
        foreign_keys="FunctionalLocation.parent_id",
        back_populates="children",
        remote_side="FunctionalLocation.id",
    )
    failure_modes = relationship("FailureMode", back_populates="functional_location")


class FailureMode(Base):
    __tablename__ = "failure_mode"

    id = Column(String, primary_key=True, default=_uuid)
    functional_location_id = Column(String, ForeignKey("functional_location.id"))
    function = Column(Text)
    functional_failure = Column(Text)
    failure_mode = Column(Text)
    failure_effect = Column(Text)
    criticality = Column(String)

    functional_location = relationship("FunctionalLocation", back_populates="failure_modes")
    tasks = relationship("Task", back_populates="failure_mode")


class Task(Base):
    __tablename__ = "task"

    id = Column(String, primary_key=True, default=_uuid)
    failure_mode_id = Column(String, ForeignKey("failure_mode.id"))
    task_type = Column(String)
    description = Column(Text)
    interval = Column(Integer)
    interval_unit = Column(String)
    duration_hours = Column(Float, default=1.0)
    resource_type = Column(String)
    is_online = Column(Boolean, default=True)
    is_regulatory = Column(Boolean, default=False)
    materials = Column(Text)
    dataset_id = Column(String)

    failure_mode = relationship("FailureMode", back_populates="tasks")


# ── Domain 2: Rules ───────────────────────────────────────────────────────────

class RuleSet(Base):
    __tablename__ = "rule_set"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    description = Column(Text)
    created_date = Column(DateTime, default=datetime.utcnow)

    rules = relationship("Rule", back_populates="rule_set", cascade="all, delete-orphan")


class Rule(Base):
    __tablename__ = "rule"

    id = Column(String, primary_key=True, default=_uuid)
    rule_set_id = Column(String, ForeignKey("rule_set.id"))
    rule_type = Column(String)
    description = Column(Text)
    parameter_key = Column(String)
    parameter_value = Column(String)
    sort_order = Column(Integer, default=0)

    rule_set = relationship("RuleSet", back_populates="rules")


# ── Domain 3: SAP Output ──────────────────────────────────────────────────────

class MaintenancePlan(Base):
    __tablename__ = "maintenance_plan"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, nullable=False)
    name = Column(String)
    description = Column(Text)
    planner_group_id = Column(String, ForeignKey("planner_group.id"), nullable=True)
    work_center_id = Column(String, ForeignKey("work_center.id"), nullable=True)

    items = relationship("MaintenancePlanItem", back_populates="plan",
                         cascade="all, delete-orphan")
    planner_group = relationship("PlannerGroup")
    work_center = relationship("WorkCenter")


class MaintenancePlanItem(Base):
    __tablename__ = "maintenance_plan_item"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, nullable=False)
    maintenance_plan_id = Column(String, ForeignKey("maintenance_plan.id"))
    frequency = Column(Integer)
    frequency_unit = Column(String)
    description = Column(Text)
    is_regulatory = Column(Boolean, default=False)
    is_online = Column(Boolean, default=True)
    total_duration_hours = Column(Float, default=0.0)

    plan = relationship("MaintenancePlan", back_populates="items")
    task_list = relationship("TaskList", back_populates="item", uselist=False,
                             cascade="all, delete-orphan")


class TaskList(Base):
    __tablename__ = "task_list"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, nullable=False)
    maintenance_plan_item_id = Column(String, ForeignKey("maintenance_plan_item.id"))
    name = Column(String)

    item = relationship("MaintenancePlanItem", back_populates="task_list")
    operations = relationship("Operation", back_populates="task_list",
                              cascade="all, delete-orphan",
                              order_by="Operation.operation_no")


class Operation(Base):
    __tablename__ = "operation"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, nullable=False)
    task_list_id = Column(String, ForeignKey("task_list.id"))
    operation_no = Column(Integer)
    source_task_id = Column(String, ForeignKey("task.id"))
    description = Column(Text)
    duration_hours = Column(Float)
    resource_type = Column(String)
    materials = Column(Text)
    document_ref = Column(String)

    task_list = relationship("TaskList", back_populates="operations")
    source_task = relationship("Task")


# ── Domain 4: SAP Reference ───────────────────────────────────────────────────

class PlannerGroup(Base):
    __tablename__ = "planner_group"

    id = Column(String, primary_key=True, default=_uuid)
    code = Column(String, nullable=False)
    description = Column(Text)
    plant = Column(String)


class WorkCenter(Base):
    __tablename__ = "work_center"

    id = Column(String, primary_key=True, default=_uuid)
    code = Column(String, nullable=False)
    description = Column(Text)
    plant = Column(String)
    resource_type = Column(String)
