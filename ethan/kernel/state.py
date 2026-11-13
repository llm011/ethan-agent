"""
长程任务状态管理系统 - 支持断点续传和长时间运行

设计原则：
1. 所有任务都有明确的状态机
2. 关键节点自动保存检查点
3. 支持暂停/恢复/取消
4. 状态持久化到数据库
5. 崩溃后自动恢复
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import asyncio
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
import pickle

logger = logging.getLogger(__name__)


# ========== 任务状态枚举 ==========

class TaskState(Enum):
    """任务状态机"""
    PENDING = "pending"          # 等待执行
    RUNNING = "running"          # 正在执行
    PAUSED = "paused"            # 已暂停
    RESUMING = "resuming"        # 正在恢复
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消
    TIMEOUT = "timeout"          # 超时
    
    @property
    def is_terminal(self) -> bool:
        """是否是终态"""
        return self in (TaskState.COMPLETED, TaskState.FAILED, 
                       TaskState.CANCELLED, TaskState.TIMEOUT)
    
    @property
    def can_resume(self) -> bool:
        """是否可以恢复"""
        return self in (TaskState.PAUSED, TaskState.FAILED, TaskState.TIMEOUT)


@dataclass
class Checkpoint:
    """任务检查点"""
    step: int
    timestamp: float
    state: str
    data: Dict[str, Any]
    context_snapshot: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "timestamp": self.timestamp,
            "state": self.state,
            "data": self._serialize_data(self.data),
            "context_snapshot": self.context_snapshot,
            "metadata": self.metadata,
        }
    
    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'Checkpoint':
        return Checkpoint(
            step=d["step"],
            timestamp=d["timestamp"],
            state=d["state"],
            data=Checkpoint._deserialize_data(d["data"]),
            context_snapshot=d.get("context_snapshot"),
            metadata=d.get("metadata", {}),
        )
    
    @staticmethod
    def _serialize_data(data: Any) -> str:
        """序列化数据为 JSON 字符串"""
        try:
            return json.dumps(data, default=str)
        except Exception as e:
            logger.warning(f"Failed to serialize checkpoint data: {e}")
            return pickle.dumps(data).hex()
    
    @staticmethod
    def _deserialize_data(data_str: str) -> Any:
        """反序列化数据"""
        try:
            return json.loads(data_str)
        except:
            return pickle.loads(bytes.fromhex(data_str))


@dataclass
class Task:
    """任务对象"""
    task_id: str
    prompt: str
    state: TaskState = TaskState.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    checkpoints: List[Checkpoint] = field(default_factory=list)
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def save_checkpoint(self, step: int, data: Dict[str, Any], 
                       context_snapshot: Optional[Dict[str, Any]] = None) -> Checkpoint:
        """保存检查点"""
        checkpoint = Checkpoint(
            step=step,
            timestamp=time.time(),
            state=self.state.value,
            data=data,
            context_snapshot=context_snapshot,
        )
        self.checkpoints.append(checkpoint)
        self.updated_at = time.time()
        return checkpoint
    
    def update_state(self, new_state: TaskState) -> None:
        """更新任务状态"""
        old_state = self.state
        self.state = new_state
        self.updated_at = time.time()
        
        if new_state == TaskState.RUNNING and self.started_at is None:
            self.started_at = self.updated_at
        elif new_state.is_terminal:
            self.completed_at = self.updated_at
        
        logger.info(f"Task {self.task_id}: {old_state.value} → {new_state.value}")


class TaskStateManager:
    """任务状态管理器 - 管理所有任务的生命周期"""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("~/.ethan/tasks.db").expanduser()
        self._tasks: Dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self._init_database()
    
    def _init_database(self) -> None:
        """初始化 SQLite 数据库"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                result TEXT,
                error TEXT,
                metadata TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                step INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                state TEXT NOT NULL,
                data TEXT NOT NULL,
                context_snapshot TEXT,
                metadata TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_state ON tasks(state)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoint_task ON checkpoints(task_id)")
        
        conn.commit()
        conn.close()
    
    async def create_task(self, task_id: str, prompt: str, 
                         metadata: Optional[Dict[str, Any]] = None) -> Task:
        """创建新任务"""
        async with self._lock:
            task = Task(
                task_id=task_id,
                prompt=prompt,
                metadata=metadata or {},
            )
            
            # 保存到内存
            self._tasks[task_id] = task
            
            # 持久化到数据库
            await self._persist_task(task)
            
            logger.info(f"Created task: {task_id}")
            return task
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        async with self._lock:
            if task_id not in self._tasks:
                # 从数据库加载
                task = await self._load_from_db(task_id)
                if task:
                    self._tasks[task_id] = task
                return task
            
            return self._tasks.get(task_id)
    
    async def update_task_state(self, task_id: str, new_state: TaskState) -> Task:
        """更新任务状态"""
        async with self._lock:
            task = await self.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            
            task.update_state(new_state)
            await self._persist_task(task)
            
            return task
    
    async def save_checkpoint(self, task_id: str, step: int, 
                             data: Dict[str, Any],
                             context_snapshot: Optional[Dict[str, Any]] = None) -> Checkpoint:
        """保存检查点"""
        async with self._lock:
            task = await self.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            
            checkpoint = task.save_checkpoint(step, data, context_snapshot)
            await self._persist_checkpoint(task_id, checkpoint)
            
            return checkpoint
    
    async def load_checkpoint(self, task_id: str, step: int) -> Optional[Checkpoint]:
        """加载指定步骤的检查点"""
        task = await self.get_task(task_id)
        if not task:
            return None
        
        for cp in task.checkpoints:
            if cp.step == step:
                return cp
        
        # 从数据库加载
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM checkpoints WHERE task_id=? AND step=?",
            (task_id, step)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Checkpoint.from_dict({
                "step": row[2],
                "timestamp": row[3],
                "state": row[4],
                "data": row[5],
                "context_snapshot": row[6],
                "metadata": json.loads(row[7]) if row[7] else {},
            })
        
        return None
    
    async def resume_from_checkpoint(self, task_id: str, 
                                    checkpoint_step: int = -1) -> Tuple[int, Checkpoint]:
        """从最近的检查点恢复任务"""
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        if not task.checkpoints:
            raise ValueError(f"No checkpoints for task {task_id}")
        
        # 获取最近的检查点
        if checkpoint_step < 0:
            checkpoint = max(task.checkpoints, key=lambda cp: cp.step)
        else:
            checkpoint = next((cp for cp in task.checkpoints if cp.step == checkpoint_step), None)
            if not checkpoint:
                raise ValueError(f"Checkpoint step {checkpoint_step} not found")
        
        # 更新状态
        await self.update_task_state(task_id, TaskState.RESUMING)
        
        logger.info(f"Resuming task {task_id} from step {checkpoint.step}")
        return checkpoint.step, checkpoint
    
    async def complete_task(self, task_id: str, result: Any) -> Task:
        """完成任务"""
        async with self._lock:
            task = await self.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            
            task.result = result
            task.update_state(TaskState.COMPLETED)
            await self._persist_task(task)
            
            return task
    
    async def fail_task(self, task_id: str, error: str) -> Task:
        """标记任务失败"""
        async with self._lock:
            task = await self.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            
            task.error = error
            task.update_state(TaskState.FAILED)
            await self._persist_task(task)
            
            return task
    
    async def list_tasks(self, state: Optional[TaskState] = None) -> List[Task]:
        """列出任务"""
        async with self._lock:
            if state:
                return [t for t in self._tasks.values() if t.state == state]
            return list(self._tasks.values())
    
    async def cleanup_old_tasks(self, days: int = 30) -> int:
        """清理旧任务"""
        cutoff = time.time() - (days * 86400)
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute(
            "DELETE FROM tasks WHERE completed_at < ? AND state IN (?, ?, ?, ?)",
            (cutoff, TaskState.COMPLETED.value, TaskState.FAILED.value,
             TaskState.CANCELLED.value, TaskState.TIMEOUT.value)
        )
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        logger.info(f"Cleaned up {deleted} old tasks")
        return deleted
    
    async def _persist_task(self, task: Task) -> None:
        """持久化任务到数据库"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO tasks 
            (task_id, prompt, state, created_at, updated_at, started_at, 
             completed_at, result, error, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task.task_id,
            task.prompt,
            task.state.value,
            task.created_at,
            task.updated_at,
            task.started_at,
            task.completed_at,
            json.dumps(task.result, default=str) if task.result else None,
            task.error,
            json.dumps(task.metadata),
        ))
        
        conn.commit()
        conn.close()
    
    async def _persist_checkpoint(self, task_id: str, checkpoint: Checkpoint) -> None:
        """持久化检查点到数据库"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO checkpoints 
            (task_id, step, timestamp, state, data, context_snapshot, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            checkpoint.step,
            checkpoint.timestamp,
            checkpoint.state,
            checkpoint.data,
            json.dumps(checkpoint.context_snapshot) if checkpoint.context_snapshot else None,
            json.dumps(checkpoint.metadata),
        ))
        
        conn.commit()
        conn.close()
    
    async def _load_from_db(self, task_id: str) -> Optional[Task]:
        """从数据库加载任务"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return None
        
        task = Task(
            task_id=row[0],
            prompt=row[1],
            state=TaskState(row[2]),
            created_at=row[3],
            updated_at=row[4],
            started_at=row[5],
            completed_at=row[6],
            result=json.loads(row[7]) if row[7] else None,
            error=row[8],
            metadata=json.loads(row[9]) if row[9] else {},
        )
        
        # 加载检查点
        cursor.execute("SELECT * FROM checkpoints WHERE task_id=? ORDER BY step", (task_id,))
        checkpoints = []
        for cp_row in cursor.fetchall():
            checkpoints.append(Checkpoint.from_dict({
                "step": cp_row[2],
                "timestamp": cp_row[3],
                "state": cp_row[4],
                "data": cp_row[5],
                "context_snapshot": json.loads(cp_row[6]) if cp_row[6] else None,
                "metadata": json.loads(cp_row[7]) if cp_row[7] else {},
            }))
        
        task.checkpoints = checkpoints
        
        conn.close()
        return task


# 全局任务管理器
_global_task_manager: Optional[TaskStateManager] = None


def get_task_manager() -> TaskStateManager:
    """获取全局任务管理器"""
    global _global_task_manager
    if _global_task_manager is None:
        _global_task_manager = TaskStateManager()
    return _global_task_manager


async def reset_task_manager() -> None:
    """重置全局任务管理器（用于测试）"""
    global _global_task_manager
    _global_task_manager = None
