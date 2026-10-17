import React, { useState, useEffect } from 'react';
import {
  Plane,
  Truck,
  Box,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  RefreshCw,
  ShieldCheck,
  Package,
  Layers,
  ArrowRight,
  Database,
  Cpu,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  MessageSquare,
  Send
} from 'lucide-react';

interface WorkflowStep {
  id: number;
  order_id: string;
  step_name: string;
  tool_name: string;
  status: 'SUCCESS' | 'WARNING' | 'FAILED' | 'RECOVERED';
  input_payload: any;
  output_payload: any;
  elapsed_ms: number;
  timestamp: string;
}

interface OrderItem {
  product_id: string;
  product_name: string;
  quantity: number;
  unit_price: number;
  weight_kg: number;
  is_fragile: boolean;
  is_hazmat: boolean;
  bin_location: string;
}

interface VerificationResult {
  is_valid: boolean;
  order_persisted: boolean;
  reservations_intact: boolean;
  inventory_delta_valid: boolean;
  carrier_tracking_verified: boolean;
  timeline_steps_count: number;
  checksum: string;
  details: any;
}

interface OrderDetail {
  id: string;
  idempotency_key?: string;
  raw_prompt: string;
  customer_name: string;
  destination_city: string;
  destination_address: string;
  priority: string;
  status: string;
  warehouse_id?: string;
  warehouse_name?: string;
  packaging_id?: string;
  packaging_name?: string;
  carrier_id?: string;
  carrier_name?: string;
  tracking_id?: string;
  total_weight_kg: number;
  total_cost: number;
  failure_reason?: string;
  items: OrderItem[];
  timeline: WorkflowStep[];
  verification?: VerificationResult;
  report?: {
    outcome: string;
    total_elapsed_ms: number;
    steps: number;
    recovered: boolean;
    llm_assisted_steps: number;
    mcp_calls: number;
    route?: { source: string; distance_km: number; eta_days: number; simulated: boolean } | null;
    summary: string;
  };
  created_at: string;
}

interface Scenario {
  id: string;
  title: string;
  badge: string;
  badge_color: 'emerald' | 'amber' | 'purple' | 'blue';
  prompt: string;
  description: string;
  simulate_carrier_failure: boolean;
  priority: string;
  idempotency_key?: string;
}

interface StockItem {
  warehouse_id: string;
  warehouse_name: string;
  city: string;
  state: string;
  product_id: string;
  product_name: string;
  sku: string;
  total_stock: number;
  reserved_stock: number;
  available_stock: number;
  bin_location: string;
}

interface Carrier {
  id: string;
  name: string;
  service_level: string;
  reliability_rating: number;
  supports_fragile: boolean;
  supports_hazmat: boolean;
  is_active: boolean;
  simulate_failure: boolean;
}

export default function App() {
  const [prompt, setPrompt] = useState<string>(
    'Ship 2 Industrial LiDAR Scanners and 1 Thermal Imaging Core to Chicago hub via express freight.'
  );
  const [priority, setPriority] = useState<string>('EXPRESS');
  const [simulateCarrierFailure, setSimulateCarrierFailure] = useState<boolean>(false);
  const [idempotencyKey, setIdempotencyKey] = useState<string>('');

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [currentOrder, setCurrentOrder] = useState<OrderDetail | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [inventory, setInventory] = useState<StockItem[]>([]);
  const [carriers, setCarriers] = useState<Carrier[]>([]);
  const [pastOrders, setPastOrders] = useState<any[]>([]);
  const [expandedPayloads, setExpandedPayloads] = useState<Record<number, boolean>>({});
  const [notification, setNotification] = useState<string | null>(null);
  const [agentInfo, setAgentInfo] = useState<any>(null);
  const [chatLog, setChatLog] = useState<{ role: 'user' | 'agent'; text: string; meta?: string }[]>([]);
  const [chatInput, setChatInput] = useState<string>('');
  const [chatLoading, setChatLoading] = useState<boolean>(false);

  const handleChat = async (e: React.FormEvent) => {
    e.preventDefault();
    const msg = chatInput.trim();
    if (!msg) return;
    setChatLog(l => [...l, { role: 'user', text: msg }]);
    setChatInput('');
    setChatLoading(true);
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Chat failed');
      const meta = `${data.source}${data.model ? ' · ' + data.model : ''}${data.actions?.length ? ' · tools: ' + data.actions.join(', ') : ''}`;
      setChatLog(l => [...l, { role: 'agent', text: data.reply, meta }]);
      if (data.order_id) await handleSelectPastOrder(data.order_id);
      await fetchInitialData();
    } catch (err: any) {
      setChatLog(l => [...l, { role: 'agent', text: `Error: ${err.message}` }]);
    } finally {
      setChatLoading(false);
    }
  };

  const handleRunScenario = (s: Scenario) => {
    handleApplyScenario(s);
    handleExecuteShipment(undefined, {
      raw_prompt: s.prompt,
      priority: s.priority,
      simulate_carrier_failure: s.simulate_carrier_failure,
      ...(s.idempotency_key ? { idempotency_key: s.idempotency_key } : {})
    });
  };

  // Fetch initial state
  useEffect(() => {
    fetchInitialData();
  }, []);

  const fetchInitialData = async () => {
    try {
      const [scenRes, invRes, carRes, ordRes] = await Promise.all([
        fetch('/api/demo/scenarios'),
        fetch('/api/inventory'),
        fetch('/api/carriers'),
        fetch('/api/shipments')
      ]);

      if (scenRes.ok) setScenarios(await scenRes.json());
      if (invRes.ok) setInventory(await invRes.json());
      if (carRes.ok) setCarriers(await carRes.json());
      if (ordRes.ok) setPastOrders(await ordRes.json());
      const infoRes = await fetch('/api/agent/info');
      if (infoRes.ok) setAgentInfo(await infoRes.json());
    } catch (err) {
      console.error('Error fetching initial data:', err);
    }
  };

  const showNotification = (msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(null), 4000);
  };

  const handleApplyScenario = (scenario: Scenario) => {
    setPrompt(scenario.prompt);
    setPriority(scenario.priority);
    setSimulateCarrierFailure(scenario.simulate_carrier_failure);
    setIdempotencyKey(scenario.idempotency_key || '');
    showNotification(`Scenario loaded: ${scenario.title}`);
  };

  const handleResetDemo = async () => {
    if (!window.confirm('Reset demo database? This will clear past shipments and restore full stock.')) return;
    try {
      setIsLoading(true);
      const res = await fetch('/api/demo/reset', { method: 'POST' });
      if (res.ok) {
        setCurrentOrder(null);
        await fetchInitialData();
        showNotification('Demo database successfully reset to clean seed state.');
      }
    } catch (err) {
      console.error('Reset error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleCarrierFailure = async (carrierId: string) => {
    try {
      const res = await fetch(`/api/carriers/${carrierId}/toggle-failure`, { method: 'POST' });
      if (res.ok) {
        const carRes = await fetch('/api/carriers');
        if (carRes.ok) setCarriers(await carRes.json());
        showNotification(`Carrier failure toggle updated.`);
      }
    } catch (err) {
      console.error('Error toggling carrier:', err);
    }
  };

  const handleExecuteShipment = async (e?: React.FormEvent, override?: any) => {
    if (e) e.preventDefault();
    if (!override && !prompt.trim()) return;

    setIsLoading(true);
    try {
      const payload: any = override ?? {
        raw_prompt: prompt,
        priority: priority,
        simulate_carrier_failure: simulateCarrierFailure
      };
      if (!override && idempotencyKey.trim()) {
        payload.idempotency_key = idempotencyKey.trim();
      }

      const res = await fetch('/api/shipments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Dispatch failed');
      }

      const orderData: OrderDetail = await res.json();
      setCurrentOrder(orderData);
      showNotification(`Shipment ${orderData.id} workflow completed.`);

      // Refresh inventory and shipment list
      const [invRes, ordRes] = await Promise.all([
        fetch('/api/inventory'),
        fetch('/api/shipments')
      ]);
      if (invRes.ok) setInventory(await invRes.json());
      if (ordRes.ok) setPastOrders(await ordRes.json());
    } catch (err: any) {
      alert(`Workflow Error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectPastOrder = async (orderId: string) => {
    try {
      const res = await fetch(`/api/shipments/${orderId}`);
      if (res.ok) {
        setCurrentOrder(await res.json());
      }
    } catch (err) {
      console.error('Error fetching order detail:', err);
    }
  };

  const togglePayloadExpand = (stepId: number) => {
    setExpandedPayloads(prev => ({ ...prev, [stepId]: !prev[stepId] }));
  };

  // Group inventory by warehouse
  const eastInventory = inventory.filter(i => i.warehouse_id === 'WH-EAST');
  const westInventory = inventory.filter(i => i.warehouse_id === 'WH-WEST');

  return (
    <div className="app-layout">
      {/* Top Header */}
      <header className="top-header">
        <div className="brand-section">
          <div className="brand-icon">
            <Cpu size={26} />
          </div>
          <div>
            <h1 className="brand-title">LOGISTICS AUTOPILOT</h1>
            <div className="brand-subtitle">Autonomous Logistics Orchestrator • GDG Hackathon MVP</div>
          </div>
        </div>

        <div className="header-badges">
          <span className="pill-status">
            <span className="pulse-dot"></span>
            API · MCP {agentInfo?.mcp_connected ? `${agentInfo.mcp_tools.length} TOOLS` : 'DOWN'} · {agentInfo?.llm_enabled ? 'GEMINI' : 'DETERMINISTIC'} · MAPS {agentInfo?.maps_enabled ? 'LIVE' : 'SIM'}
          </span>
          <span className="pill-status" style={{ borderColor: 'rgba(59, 130, 246, 0.3)', color: '#60a5fa', background: 'rgba(59, 130, 246, 0.1)' }}>
            <Database size={13} style={{ marginRight: '3px' }} />
            SQLITE WAL
          </span>
          <button className="btn-reset" onClick={handleResetDemo} disabled={isLoading} title="Restore full stock and clear active dispatches">
            <RotateCcw size={14} />
            DEMO RESET
          </button>
        </div>
      </header>

      {/* Notification Toast */}
      {notification && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          zIndex: 9999,
          background: '#1e293b',
          color: '#38bdf8',
          border: '1px solid #38bdf8',
          padding: '0.75rem 1.25rem',
          borderRadius: '8px',
          boxShadow: '0 8px 25px rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.85rem'
        }}>
          <CheckCircle2 size={16} />
          {notification}
        </div>
      )}

      {/* Predefined Scenarios Bar */}
      <section className="scenarios-container">
        <div className="section-label">
          <Layers size={14} /> Predefined Test Scenarios (1-Click Evaluation)
        </div>
        <div className="scenarios-grid">
          {scenarios.map(s => (
            <div
              key={s.id}
              className={`scenario-card ${s.badge_color}`}
              onClick={() => handleApplyScenario(s)}
            >
              <div>
                <div className="scenario-header">
                  <span className="scenario-title">{s.title}</span>
                  <span className={`badge badge-${s.badge_color}`}>{s.badge}</span>
                </div>
                <p className="scenario-desc">{s.description}</p>
              </div>
              <div className="scenario-action-hint" style={{ justifyContent: 'space-between' }}>
                <span>Load into cockpit <ArrowRight size={13} /></span>
                <button
                  className="btn-run-scenario"
                  id={`run-${s.id}`}
                  disabled={isLoading}
                  onClick={(ev) => { ev.stopPropagation(); handleRunScenario(s); }}
                >
                  Run now
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Natural Language Shipment Dispatch Bar */}
      <section className="dispatch-box">
        <form onSubmit={handleExecuteShipment}>
          <div className="dispatch-input-row">
            <textarea
              className="prompt-textarea"
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder="Enter natural language shipment instruction (e.g. 'Ship 2 Industrial LiDAR Scanners and 1 Battery Pack to Chicago hub overnight')..."
              rows={2}
            />
            <button type="submit" className="btn-dispatch" disabled={isLoading}>
              {isLoading ? (
                <>
                  <RefreshCw size={20} className="animate-spin" />
                  <span>AUTOPILOTING...</span>
                </>
              ) : (
                <>
                  <Plane size={20} />
                  <span>DISPATCH</span>
                </>
              )}
            </button>
          </div>

          <div className="dispatch-options-row">
            <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', flexWrap: 'wrap' }}>
              <div>
                <label style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginRight: '6px' }}>Priority:</label>
                <select
                  value={priority}
                  onChange={e => setPriority(e.target.value)}
                  style={{
                    background: 'var(--bg-surface)',
                    color: 'var(--text-primary)',
                    border: '1px solid var(--border-subtle)',
                    padding: '0.3rem 0.6rem',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.8rem'
                  }}
                >
                  <option value="STANDARD">STANDARD (Ground)</option>
                  <option value="EXPRESS">EXPRESS (Air Priority)</option>
                  <option value="URGENT">URGENT (Overnight Critical)</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginRight: '6px' }}>Idempotency Key:</label>
                <input
                  type="text"
                  placeholder="(Auto-generated if empty)"
                  value={idempotencyKey}
                  onChange={e => setIdempotencyKey(e.target.value)}
                  style={{
                    background: 'var(--bg-surface)',
                    color: 'var(--text-primary)',
                    border: '1px solid var(--border-subtle)',
                    padding: '0.3rem 0.6rem',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.8rem',
                    width: '180px',
                    fontFamily: 'var(--font-mono)'
                  }}
                />
              </div>
            </div>

            <div className="toggle-group">
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={simulateCarrierFailure}
                  onChange={e => setSimulateCarrierFailure(e.target.checked)}
                />
                <span className="toggle-slider"></span>
              </label>
              <span style={{ color: simulateCarrierFailure ? '#fbbf24' : 'var(--text-secondary)', fontWeight: 600 }}>
                Simulate Carrier Outage (Triggers Autonomous Recovery)
              </span>
            </div>
          </div>
        </form>
      </section>

      {/* Main Content Dashboard */}
      <div className="dashboard-grid">
        {/* Left Column: Active Order Workflow Execution Timeline */}
        <div>
          <div className="panel-card">
            <div className="panel-header">
              <div className="panel-title">
                <Cpu size={20} color="#6366f1" />
                Autonomous Workflow Execution Timeline
              </div>
              {currentOrder && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: '#93c5fd' }}>
                    {currentOrder.id}
                  </span>
                  <span className={`badge ${currentOrder.status === 'COMPLETED' ? 'badge-emerald' : currentOrder.status === 'FAILED' ? 'badge-amber' : 'badge-blue'}`}>
                    {currentOrder.status}
                  </span>
                </div>
              )}
            </div>

            {!currentOrder && (
              <div style={{
                padding: '3rem 1.5rem',
                textAlign: 'center',
                color: 'var(--text-muted)',
                background: 'rgba(255, 255, 255, 0.01)',
                borderRadius: 'var(--radius-md)',
                border: '1px dashed var(--border-subtle)'
              }}>
                <Box size={40} style={{ margin: '0 auto 1rem', opacity: 0.4 }} />
                <p style={{ fontWeight: 600, fontSize: '0.95rem' }}>No active execution in session</p>
                <p style={{ fontSize: '0.8rem', marginTop: '0.35rem' }}>
                  Click one of the predefined scenario cards above or enter an instruction and hit Dispatch.
                </p>
              </div>
            )}

            {currentOrder && (
              <div>
                {/* Items Summary Bar */}
                <div style={{
                  background: 'var(--bg-surface)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.85rem 1rem',
                  marginBottom: '1.25rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  fontSize: '0.82rem',
                  border: '1px solid var(--border-subtle)'
                }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Destination: </span>
                    <strong style={{ color: 'var(--text-primary)' }}>{currentOrder.destination_city}</strong>
                    <span style={{ color: 'var(--text-muted)', marginLeft: '12px' }}>Items: </span>
                    <strong>{currentOrder.items.map(i => `${i.quantity}x ${i.product_name}`).join(', ') || 'N/A'}</strong>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Weight: </span>
                    <strong>{currentOrder.total_weight_kg} kg</strong>
                    <span style={{ color: 'var(--text-muted)', marginLeft: '12px' }}>Est. Cost: </span>
                    <strong style={{ color: '#34d399' }}>${currentOrder.total_cost}</strong>
                  </div>
                </div>

                {/* Final Execution Report */}
                {currentOrder.report && (
                  <div className="report-card" id="execution-report">
                    <div className="report-title">Execution Report · {currentOrder.report.outcome}</div>
                    <p className="report-summary">{currentOrder.report.summary}</p>
                    <div className="report-stats">
                      <span>{currentOrder.report.steps} steps</span>
                      <span>{currentOrder.report.total_elapsed_ms} ms tool time</span>
                      <span>{currentOrder.report.mcp_calls} MCP calls</span>
                      <span>{currentOrder.report.llm_assisted_steps} LLM-assisted</span>
                      <span>{currentOrder.report.recovered ? 'self-healed' : 'no recovery needed'}</span>
                      {currentOrder.report.route && (
                        <span>{currentOrder.report.route.distance_km} km · ETA {currentOrder.report.route.eta_days}d ({currentOrder.report.route.simulated ? 'simulated' : 'Google Maps'})</span>
                      )}
                    </div>
                  </div>
                )}

                {/* Timeline Steps */}
                <div className="timeline-list">
                  {currentOrder.timeline.map((step) => {
                    const isExpanded = expandedPayloads[step.id] || false;
                    let icon = <CheckCircle2 size={18} />;
                    let itemClass = 'success';

                    if (step.status === 'WARNING') {
                      icon = <AlertTriangle size={18} />;
                      itemClass = 'warning';
                    } else if (step.status === 'RECOVERED') {
                      icon = <RefreshCw size={18} />;
                      itemClass = 'recovered';
                    } else if (step.status === 'FAILED') {
                      icon = <AlertCircle size={18} />;
                      itemClass = 'failed';
                    }

                    return (
                      <div key={step.id} className={`timeline-item ${itemClass}`}>
                        <div className="timeline-icon-wrap">
                          {icon}
                        </div>
                        <div className="timeline-content">
                          <div className="timeline-top">
                            <span className="step-label">{step.step_name.replace(/_/g, ' ')}</span>
                            <div className="step-meta">
                              <span className="tool-tag">{step.tool_name}</span>
                              {step.output_payload?.meta?.transport && (
                                <span className="tool-tag" style={{ background: 'rgba(6,182,212,0.15)', color: '#67e8f9' }}>{step.output_payload.meta.transport}</span>
                              )}
                              {step.output_payload?.parse_source && (
                                <span className="tool-tag" style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd' }}>parse: {step.output_payload.parse_source}</span>
                              )}
                              <span className="elapsed-tag">{step.elapsed_ms}ms</span>
                            </div>
                          </div>

                          <div className="step-summary">
                            {step.status === 'FAILED' && (
                              <span style={{ color: '#fb7185' }}>{step.output_payload.error || 'Step failed'}</span>
                            )}
                            {step.status === 'WARNING' && (
                              <span style={{ color: '#fbbf24' }}>
                                Carrier outage: {step.output_payload.error || 'Connection failed'}.{' '}
                                {step.output_payload.diagnosis && (
                                  <>Diagnosis ({step.output_payload.diagnosis.source}{step.output_payload.diagnosis.model ? ` · ${step.output_payload.diagnosis.model}` : ''}): retry with <strong>{step.output_payload.diagnosis.carrier_id}</strong>. {step.output_payload.diagnosis.reason}</>
                                )}
                              </span>
                            )}
                            {step.status === 'RECOVERED' && (
                              <span style={{ color: '#22d3ee' }}>
                                Autonomous recovery successful: Dispatched via {step.output_payload.carrier_name} (Tracking: {step.output_payload.tracking_id}).
                              </span>
                            )}
                            {step.status === 'SUCCESS' && step.step_name === 'ORDER_VALIDATED' && (
                              <span>Order catalog validated for destination {step.output_payload.destination_city}.</span>
                            )}
                            {step.status === 'SUCCESS' && step.step_name === 'INVENTORY_EVALUATED' && (
                              <span>Optimal fulfillment warehouse: {step.output_payload.selected_warehouse_id}.</span>
                            )}
                            {step.status === 'SUCCESS' && step.step_name === 'INVENTORY_RESERVED' && (
                              <span>Reserved {step.output_payload.reserved_count} item(s) atomically in SQLite.</span>
                            )}
                            {step.status === 'SUCCESS' && step.step_name === 'ITEMS_PICKED' && (
                              <span>AGV robot picked {step.output_payload.items_picked_count} item(s) from warehouse bins.</span>
                            )}
                            {step.status === 'SUCCESS' && step.step_name === 'PACKAGING_ASSIGNED' && (
                              <span>Certified packaging selected: {step.output_payload.packaging_name} (Max {step.output_payload.max_weight_kg}kg).</span>
                            )}
                            {step.status === 'SUCCESS' && step.step_name === 'CARRIER_DISPATCHED' && (
                              <span>Booked {step.output_payload.carrier_name}. Tracking ID: <strong>{step.output_payload.tracking_id}</strong>.</span>
                            )}
                            {step.status === 'SUCCESS' && step.step_name === 'PERSISTED_STATE_VERIFIED' && (
                              <span>Order, reservations, carrier booking and audit trail re-read from SQLite and checked.</span>
                            )}
                            {step.step_name === 'ROUTE_PLANNED' && (
                              <span>{step.output_payload.origin} → {step.output_payload.destination}: {step.output_payload.distance_km} km, ETA {step.output_payload.eta_days}d ({step.output_payload.source}).</span>
                            )}
                            {step.output_payload?.evidence && (
                              <div style={{ marginTop: '0.3rem', fontSize: '0.72rem', color: step.output_payload.evidence.passed ? '#6ee7b7' : '#fb7185' }}>
                                Evidence ({step.output_payload.evidence.source}): {step.output_payload.evidence.check} — {step.output_payload.evidence.passed ? 'confirmed' : 'MISMATCH'}
                              </div>
                            )}
                          </div>

                          <div style={{ marginTop: '0.4rem' }}>
                            <button
                              onClick={() => togglePayloadExpand(step.id)}
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: 'var(--text-muted)',
                                fontSize: '0.72rem',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '3px'
                              }}
                            >
                              {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                              {isExpanded ? 'Hide Payload' : 'Inspect Input/Output Payload'}
                            </button>

                            {isExpanded && (
                              <pre className="payload-inspector">
                                {JSON.stringify({ input: step.input_payload, output: step.output_payload }, null, 2)}
                              </pre>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Final Verification Certificate */}
                {currentOrder.verification && (
                  <div className="verification-card">
                    <div className="verif-header">
                      <div className="verif-title">
                        <ShieldCheck size={22} />
                        Persisted Backend State Verification
                      </div>
                      <span className="checksum-pill">{currentOrder.verification.checksum}</span>
                    </div>

                    <div className="verif-checks-grid">
                      <div className="verif-check-item ok">
                        <CheckCircle2 size={14} />
                        <span>Orders table persisted in SQLite</span>
                      </div>
                      <div className="verif-check-item ok">
                        <CheckCircle2 size={14} />
                        <span>Inventory atomic balance delta verified</span>
                      </div>
                      <div className="verif-check-item ok">
                        <CheckCircle2 size={14} />
                        <span>Active carrier tracking ID validated</span>
                      </div>
                      <div className="verif-check-item ok">
                        <CheckCircle2 size={14} />
                        <span>Complete workflow audit timeline ({currentOrder.verification.timeline_steps_count} steps)</span>
                      </div>
                    </div>

                    <div style={{
                      marginTop: '0.9rem',
                      paddingTop: '0.75rem',
                      borderTop: '1px solid rgba(16, 185, 129, 0.2)',
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontSize: '0.8rem',
                      color: 'var(--text-secondary)'
                    }}>
                      <div>
                        Warehouse: <strong style={{ color: 'white' }}>{currentOrder.warehouse_name || currentOrder.warehouse_id}</strong>
                      </div>
                      <div>
                        Carrier: <strong style={{ color: 'white' }}>{currentOrder.carrier_name || currentOrder.carrier_id}</strong>
                      </div>
                      <div>
                        Tracking: <strong style={{ color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>{currentOrder.tracking_id}</strong>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Warehouses, Carriers, and Dispatches */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {/* Conversational operator agent */}
          <div className="panel-card" id="chat-panel">
            <div className="panel-header">
              <div className="panel-title">
                <MessageSquare size={20} color="#22d3ee" />
                Operator Chat Agent
              </div>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                {agentInfo?.llm_enabled ? agentInfo.fast_model : 'deterministic fallback'}
              </span>
            </div>
            <div className="chat-log" id="chat-log">
              {chatLog.length === 0 && (
                <div className="chat-hint">
                  Try: "ship 2 lidar scanners to Chicago", "how much stock is left?", "where is my last shipment?", "apex is down".
                </div>
              )}
              {chatLog.map((m, i) => (
                <div key={i} className={`chat-msg ${m.role}`}>
                  <div>{m.text}</div>
                  {m.meta && <div className="chat-meta">{m.meta}</div>}
                </div>
              ))}
              {chatLoading && <div className="chat-msg agent">Working…</div>}
            </div>
            <form onSubmit={handleChat} className="chat-form">
              <input
                id="chat-input"
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                placeholder="Ask or instruct the logistics agent…"
                disabled={chatLoading}
              />
              <button type="submit" id="chat-send" disabled={chatLoading || !chatInput.trim()} title="Send">
                <Send size={16} />
              </button>
            </form>
          </div>

          {/* Warehouse Inventory Cards */}
          <div className="panel-card">
            <div className="panel-header">
              <div className="panel-title">
                <Box size={20} color="#06b6d4" />
                Live Warehouse Inventory
              </div>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                ATOMIC LOCKING
              </span>
            </div>

            <div className="inventory-section">
              {/* Alpha Hub East */}
              <div className="warehouse-card">
                <div className="wh-title-row">
                  <span className="wh-name">Alpha Hub (East Coast - Newark, NJ)</span>
                  <span className="badge badge-emerald">ACTIVE</span>
                </div>
                <table className="stock-table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Bin</th>
                      <th>Available</th>
                      <th>Reserved</th>
                    </tr>
                  </thead>
                  <tbody>
                    {eastInventory.map(item => {
                      const pct = Math.round((item.available_stock / item.total_stock) * 100);
                      return (
                        <tr key={item.product_id}>
                          <td>{item.product_name}</td>
                          <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>{item.bin_location}</td>
                          <td>
                            <div className="stock-meter-wrap">
                              <div className="stock-meter-bar" style={{ width: `${pct}%` }}></div>
                            </div>
                            <strong>{item.available_stock}</strong> / {item.total_stock}
                          </td>
                          <td>
                            {item.reserved_stock > 0 ? (
                              <span className="stock-reserved-badge">+{item.reserved_stock} reserved</span>
                            ) : (
                              <span style={{ color: 'var(--text-muted)' }}>0</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Beta Hub West */}
              <div className="warehouse-card">
                <div className="wh-title-row">
                  <span className="wh-name">Beta Hub (West Coast - Oakland, CA)</span>
                  <span className="badge badge-emerald">ACTIVE</span>
                </div>
                <table className="stock-table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Bin</th>
                      <th>Available</th>
                      <th>Reserved</th>
                    </tr>
                  </thead>
                  <tbody>
                    {westInventory.map(item => {
                      const pct = Math.round((item.available_stock / item.total_stock) * 100);
                      return (
                        <tr key={item.product_id}>
                          <td>{item.product_name}</td>
                          <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>{item.bin_location}</td>
                          <td>
                            <div className="stock-meter-wrap">
                              <div className="stock-meter-bar" style={{ width: `${pct}%`, background: '#38bdf8' }}></div>
                            </div>
                            <strong>{item.available_stock}</strong> / {item.total_stock}
                          </td>
                          <td>
                            {item.reserved_stock > 0 ? (
                              <span className="stock-reserved-badge">+{item.reserved_stock} reserved</span>
                            ) : (
                              <span style={{ color: 'var(--text-muted)' }}>0</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Carrier Fleet & Outage Simulator */}
          <div className="panel-card">
            <div className="panel-header">
              <div className="panel-title">
                <Truck size={20} color="#f59e0b" />
                Carrier Dispatch Fleet & Chaos Testing
              </div>
            </div>

            <div className="carriers-list">
              {carriers.map(c => (
                <div key={c.id} className={`carrier-item ${c.simulate_failure ? 'offline' : ''}`}>
                  <div>
                    <div className="carrier-name">{c.name}</div>
                    <div className="carrier-details">
                      Rating: {c.reliability_rating} ★ • {c.service_level} •{' '}
                      {c.supports_hazmat ? 'Hazmat Approved' : 'Standard/Fragile'}
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {c.simulate_failure ? (
                      <span className="badge badge-amber">SIMULATING 503</span>
                    ) : (
                      <span className="badge badge-emerald">ONLINE</span>
                    )}
                    <button
                      onClick={() => handleToggleCarrierFailure(c.id)}
                      style={{
                        background: c.simulate_failure ? 'rgba(245, 158, 11, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                        border: '1px solid var(--border-subtle)',
                        color: 'var(--text-secondary)',
                        padding: '0.25rem 0.5rem',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '0.7rem',
                        cursor: 'pointer'
                      }}
                      title="Toggle simulated carrier outage"
                    >
                      Toggle
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Recent Dispatches Table */}
          <div className="panel-card">
            <div className="panel-header">
              <div className="panel-title">
                <Package size={20} color="#8b5cf6" />
                Persisted Shipment Ledger ({pastOrders.length})
              </div>
            </div>

            <div style={{ overflowX: 'auto', maxHeight: '280px' }}>
              <table className="shipments-table">
                <thead>
                  <tr>
                    <th>Order ID</th>
                    <th>Destination</th>
                    <th>Carrier</th>
                    <th>Tracking</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {pastOrders.length === 0 ? (
                    <tr>
                      <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                        No orders recorded yet.
                      </td>
                    </tr>
                  ) : (
                    pastOrders.map(ord => (
                      <tr
                        key={ord.id}
                        onClick={() => handleSelectPastOrder(ord.id)}
                        style={{ cursor: 'pointer' }}
                        title="Click to view execution timeline"
                      >
                        <td style={{ fontFamily: 'var(--font-mono)' }}>{ord.id.slice(-8)}</td>
                        <td>{ord.destination_city}</td>
                        <td>{ord.carrier_name || 'N/A'}</td>
                        <td>
                          {ord.tracking_id ? (
                            <span className="trk-badge">{ord.tracking_id}</span>
                          ) : (
                            <span style={{ color: 'var(--text-muted)' }}>-</span>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${ord.status === 'COMPLETED' ? 'badge-emerald' : 'badge-amber'}`}>
                            {ord.status}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
