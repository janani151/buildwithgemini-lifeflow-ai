from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-01-7b04b331c989"


def seed_firestore():
    db = firestore.Client(project=PROJECT_ID)
    tasks_ref = db.collection("tasks")

    initial_tasks = [
        {
            "task_id": "task-001",
            "title": "Pay Electricity Bill",
            "category": "bill",
            "priority": "high",
            "due_date": "2026-09-24",
            "status": "pending",
            "details": "Amount due: $120. Pay via online portal.",
        },
        {
            "task_id": "task-002",
            "title": "Schedule Dentist Appointment",
            "category": "appointment",
            "priority": "medium",
            "due_date": "2026-09-26",
            "status": "pending",
            "details": "Routine 6-month cleaning checkup.",
        },
        {
            "task_id": "task-003",
            "title": "Buy Groceries",
            "category": "shopping",
            "priority": "medium",
            "due_date": "2026-09-25",
            "status": "pending",
            "details": "Buy fresh vegetables, fruits, and almond milk (dairy-free, gluten-free).",
        },
        {
            "task_id": "task-004",
            "title": "Weekly Workout Planning",
            "category": "personal",
            "priority": "low",
            "due_date": "2026-09-28",
            "status": "completed",
            "details": "Planned 3 cardio sessions and 2 strength training sessions.",
        },
    ]

    for task in initial_tasks:
        doc_ref = tasks_ref.document(task["task_id"])
        doc_ref.set(task)
        print(f"Seeded task: {task['task_id']} - {task['title']}")


if __name__ == "__main__":
    seed_firestore()
