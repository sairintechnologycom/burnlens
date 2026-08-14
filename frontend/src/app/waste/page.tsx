"use client";

import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";

function WasteContent() {
  return (
    <div className="card" style={{ margin: 16 }}>
      <EmptyState
        title="Waste findings are coming to the hosted dashboard"
        description="Waste findings are coming to the hosted dashboard; available today in the local dashboard via burnlens dashboard."
        code={"burnlens dashboard"}
      />
    </div>
  );
}

export default function WastePage() {
  return (
    <Shell>
      <WasteContent />
    </Shell>
  );
}
