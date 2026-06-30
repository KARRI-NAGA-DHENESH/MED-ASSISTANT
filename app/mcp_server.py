import sys
import logging
from mcp.server.fastmcp import FastMCP

# Setup logging to stderr because stdout is reserved for stdio transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("med_assistant_mcp")

mcp = FastMCP("MedAssistantMCPServer")


@mcp.tool()
def check_drug_conflicts(drugs: list[str]) -> str:
    """Checks for known clinical interactions or conflicts within a list of medications.

    Args:
        drugs: A list of drug names to check.

    Returns:
        A report detailing any known drug interactions or a safe clearance status.
    """
    logger.info(f"Checking drug conflicts for: {drugs}")
    cleaned_drugs = [d.strip().lower() for d in drugs]
    
    conflicts = []
    
    # Common severe interaction examples:
    # 1. Aspirin + Warfarin / Blood thinners
    blood_thinners = {"warfarin", "coumadin", "clopidogrel", "plavix", "apixaban", "eliquis"}
    nsaids = {"aspirin", "ibuprofen", "advil", "motrin", "naproxen", "aleve"}
    
    has_nsaid = any(d in nsaids for d in cleaned_drugs)
    has_thinner = any(d in blood_thinners for d in cleaned_drugs)
    
    if has_nsaid and has_thinner:
        conflicts.append(
            "WARNING: Combining NSAIDs (e.g., Aspirin, Ibuprofen) with blood thinners (e.g., Warfarin, Eliquis) "
            "significantly increases the risk of serious gastrointestinal bleeding. Consult your doctor immediately."
        )
        
    # 2. ACE Inhibitors (e.g., Lisinopril) + Potassium-sparing diuretics (e.g., Spironolactone) or Potassium supplements
    ace_inhibitors = {"lisinopril", "enalapril", "ramipril"}
    potassium_sparing = {"spironolactone", "aldactone"}
    
    has_ace = any(d in ace_inhibitors for d in cleaned_drugs)
    has_potassium = any(d in potassium_sparing or "potassium" in d for d in cleaned_drugs)
    
    if has_ace and has_potassium:
        conflicts.append(
            "WARNING: Co-administration of ACE Inhibitors (e.g., Lisinopril) and Potassium-sparing medications "
            "can lead to hyperkalemia (high potassium levels). Regular blood tests and doctor monitoring are required."
        )
        
    if conflicts:
        return "\n".join(conflicts)
    
    return "No major conflicts detected among the provided list of medications. Always verify with your pharmacist."


@mcp.tool()
def calculate_dose_schedule(frequency: str, start_hour: int = 8) -> list[str]:
    """Calculates daily administration times for a medication based on prescription frequency.

    Args:
        frequency: Frequency term like QD (once daily), BID (twice daily), TID (three times daily), or QID (four times daily).
        start_hour: 24-hour format starting hour (e.g., 8 for 08:00). Default is 8.

    Returns:
        A list of formatted times (e.g., ["08:00", "20:00"]).
    """
    logger.info(f"Calculating schedule for frequency={frequency}, start_hour={start_hour}")
    freq = frequency.strip().upper()
    times = []
    
    if freq == "QD":
        times = [f"{start_hour:02d}:00"]
    elif freq == "BID":
        times = [f"{start_hour:02d}:00", f"{(start_hour + 12) % 24:02d}:00"]
    elif freq == "TID":
        times = [f"{start_hour:02d}:00", f"{(start_hour + 8) % 24:02d}:00", f"{(start_hour + 16) % 24:02d}:00"]
    elif freq == "QID":
        times = [
            f"{start_hour:02d}:00",
            f"{(start_hour + 6) % 24:02d}:00",
            f"{(start_hour + 12) % 24:02d}:00",
            f"{(start_hour + 18) % 24:02d}:00"
        ]
    else:
        # Fallback to once daily
        times = [f"{start_hour:02d}:00"]
        
    return sorted(times)


@mcp.tool()
def assess_symptom_urgency(symptom: str, severity: str) -> str:
    """Assesses the clinical urgency of logged symptoms and recommends appropriate action.

    Args:
        symptom: Description of the symptom (e.g., "chest pain", "runny nose").
        severity: Subjective severity: Low, Medium, or High.

    Returns:
        An assessment message stating recommendations and urgency level.
    """
    logger.info(f"Assessing urgency for symptom={symptom}, severity={severity}")
    s = symptom.lower()
    sev = severity.lower()
    
    # Red flag symptoms
    red_flags = ["chest pain", "difficulty breathing", "shortness of breath", "numbness", "loss of speech", "severe head injury"]
    
    if any(rf in s for rf in red_flags) or sev == "high":
        return (
            "URGENCY: CRITICAL ALERT. The symptom reported is potentially life-threatening. "
            "Do not wait. Seek immediate medical attention or call emergency services (911 or local equivalent) immediately."
        )
        
    if sev == "medium":
        return (
            "URGENCY: MODERATE. Schedule an appointment with your healthcare provider. "
            "If symptoms worsen or are accompanied by a high fever, please seek urgent care."
        )
        
    return (
        "URGENCY: LOW. Continue to monitor the symptom, get rest, and stay hydrated. "
        "Log details if it persists for more than 3 days, and consult your primary care doctor at your next visit."
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
