const ACTION_TIERS = ["emergency", "actionable", "quality"];

export function filterPatients(rows, { program, status }) {
  return rows.filter((patient) => {
    if (program && patient.program !== program) return false;
    if (status === "action" && !ACTION_TIERS.includes(patient.tier)) return false;
    if (status === "overdue" && !patient.overdue) return false;
    return true;
  });
}
