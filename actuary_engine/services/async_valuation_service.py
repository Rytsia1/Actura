import asyncio
from typing import Optional
from uuid import UUID
from datetime import datetime
from actuary_engine.core.jobs import ValuationJob, JobStatus, _job_store
from actuary_engine.services.valuation_service import ValuationService
from actuary_engine.infrastructure.database import SessionLocal

class AsyncValuationService:
    @staticmethod
    def submit_job(project_id: str, contract_id: str, assumption_set_id: str, background_tasks=None) -> str:
        """Submit a valuation job and return the job ID."""
        job = ValuationJob(
            project_id=project_id,
            contract_id=contract_id,
            assumption_set_id=assumption_set_id
        )
        _job_store[job.id] = job
        
        # Start background execution
        if background_tasks:
            background_tasks.add_task(AsyncValuationService._execute_job, job.id)
        else:
            # Fallback for tests if no background_tasks is provided
            import threading
            threading.Thread(target=AsyncValuationService._execute_job, args=(job.id,)).start()
        
        return job.id

    @staticmethod
    def _execute_job(job_id: str):
        """Background task that runs the valuation (executed in a thread thread)."""
        job = _job_store[job_id]
        job.status = JobStatus.RUNNING
        job.updated_at = datetime.utcnow()
        
        db = SessionLocal()
        try:
            # Simulated progress for UI demonstration
            job.progress = 20.0
            
            # Actually run the valuation
            service = ValuationService(db)
            
            # In a real heavy Monte Carlo engine, we'd hook into progress callbacks.
            # For now, since the actual execution takes < 1 second for 100k paths, 
            # we just run it and jump to 100%.
            
            run = service.run_valuation(
                project_id=UUID(job.project_id),
                contract_id=UUID(job.contract_id),
                assumption_set_id=UUID(job.assumption_set_id) if job.assumption_set_id else None
            )
            
            job.progress = 90.0
            job.updated_at = datetime.utcnow()
            
            # Extract result payload
            if run.result:
                job.result = {
                    "bel": run.result.bel,
                    "var_95": run.result.var_95,
                    "cvar_95": run.result.cvar_95,
                    "full_output": run.result.full_output
                }
            
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            
        finally:
            db.close()
            job.updated_at = datetime.utcnow()

    @staticmethod
    def get_job_status(job_id: str) -> Optional[ValuationJob]:
        """Poll the status of a job."""
        return _job_store.get(job_id)
