const HEADLINE = {
  emergency: "Urgent - check now",
  actionable: "Please check",
  quality: "Sensor problem",
  watch: "Keep an eye on this",
  stable: "All clear",
  unknown: "No data",
};

const ANSWER = {
  done: "Done",
  cannot: "Could not do it",
  contact_doctor: "Asked for the doctor",
};

export function careHeadline(tier) {
  return HEADLINE[tier] || tier;
}

export function careAnswer(response) {
  return ANSWER[response] || response;
}
