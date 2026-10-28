// Operator test cycle definition: regulatory certificates and the CSP stages.
// Stage substages are added here once the operator test plans are defined.
(() => {
  window.OPERATOR_FLOW = {
    calendarDays: 30,

    certificates: [
      {
        id: "fcc",
        name: "FCC Certification",
        desc: "US radio-frequency equipment authorization (FCC ID grant)",
        issuers: ["Federal Communications Commission", "FCC"]
      },
      {
        id: "gcf",
        name: "GCF Certification",
        desc: "3GPP conformance for cellular radio and protocol",
        issuers: ["Global Certification Forum", "GCF"]
      },
      {
        id: "wifi",
        name: "Wi-Fi Certification",
        desc: "Wi-Fi CERTIFIED interoperability",
        issuers: ["Wi-Fi Alliance"]
      },
      {
        id: "bt",
        name: "Bluetooth Certification",
        desc: "Bluetooth qualification (Declaration ID / QDID)",
        issuers: ["Bluetooth SIG"]
      },
      {
        id: "nfc",
        name: "NFC Certification",
        desc: "NFC Forum device certification",
        issuers: ["NFC Forum"]
      },
      {
        id: "gms",
        name: "GMS (CTS)",
        desc: "Google Mobile Services licence and Compatibility Test Suite",
        issuers: ["Google"]
      },
      {
        id: "csp",
        name: "CSP Test Plan Compliance",
        desc: "Operator test plan compliance statement",
        issuers: []
      }
    ],

    stages: [
      {
        id: "pat",
        name: "PAT",
        title: "Product Acceptance Test",
        env: "lab",
        gate: "reject",
        template: "checklist",
        desc: "Pre-acceptance verification of the device against the operator's requirements.",
        substages: []
      },
      {
        id: "sfn",
        name: "SFN",
        title: "Safe for Network",
        env: "lab",
        gate: "reject",
        template: "measure",
        desc: "Measurements that confirm the device does not harm the operator network.",
        substages: []
      },
      {
        id: "functional",
        name: "Functional / Performance",
        title: "Functional and Performance Test",
        env: "lab",
        gate: "reject",
        template: "checklist",
        desc: "Core device features and performance in the lab.",
        substages: []
      },
      {
        id: "field",
        name: "Inter-Op / Field",
        title: "Inter-Operability and Field Testing",
        env: "local",
        gate: "fix",
        template: "checklist",
        desc: "Live-network testing in real locations with live SIMs.",
        substages: []
      },
      {
        id: "fut",
        name: "FUT",
        title: "Friendly User Trial",
        env: "local",
        gate: "fix",
        template: "fut",
        desc: "Real users on the operator network. Run by the OEM or by the CSP."
      },
      {
        id: "regional",
        name: "Regional",
        title: "Regional Test",
        env: "global",
        gate: "report",
        template: "checklist",
        desc: "Testing in other regions with live SIMs.",
        substages: []
      },
      {
        id: "localization",
        name: "Localization",
        title: "Localization Test",
        env: "global",
        gate: "report",
        template: "checklist",
        desc: "Language, formats and local content checks.",
        substages: []
      },
      {
        id: "approval",
        name: "Approval",
        title: "Approval",
        env: "lab",
        gate: "report",
        template: "approval",
        desc: "Final sign-off based on the consolidated results."
      }
    ]
  };
})();
