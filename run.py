import uvicorn
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("=" * 70)
    print("  BLOOD BANK MANAGEMENT SYSTEM (BBMS) - SWE PROJECT")
    print("  Student: N S LOKESH NAIDU | SRN: PES2UG24CS292 | Sec: 5E")
    print("  SRS Specification: v1.1 Verified (All Requirements BBMS-F-001..020)")
    print("=" * 70)
    print("  Web Portal URL:       http://localhost:8000")
    print("  Interactive API Docs: http://localhost:8000/docs")
    print("  Alternative Redoc:    http://localhost:8000/redoc")
    print("=" * 70)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
