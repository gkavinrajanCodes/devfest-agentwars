import React, { useState, useEffect } from 'react';
import {
  Plane,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RotateCcw,
  Package,
  Layers,
  MapPin,
  TrendingUp,
  Cpu,
  Copy,
  ChevronDown,
  ChevronRight,
  MessageSquare,
  X,
  Send,
  RefreshCw,
  Sliders,
  ShieldCheck,
  Zap,
  Box,
  Truck,
  ArrowRight,
  ExternalLink
} from 'lucide-react';

interface OrderItem {
  id?: number;
  product_id: string;
  product_name: string;
  sku: string;
  quantity: number;
  unit_price: number;
  total_price: number;
  weight_kg: number;
  is_fragile: boolean;
  is_hazmat: boolean;
}

interface StepLog {
  id: number;
  step_name: string;
  tool_called: string;
  status: 'SUCCESS' | 'FAILED' | 'RETRYING';
  duration_ms: number;
  input_payload?: any;
  output_payload?: any;
  error_message?: string;
  created_at: string;
}

interface OrderDetail {
  id: string;
  idempotency_key: string;
  raw_prompt: string;
  customer_name: string;
  destination_city: string;
  destination_address: string;
  priority: string;
  status: string;
  warehouse_id?: string;
  warehouse_name?: string;
  carrier_id?: string;
  carrier_name?: string;
  tracking_id?: string;
  packaging_id?: string;
  packaging_name?: string;
  total_weight_kg?: number;
  total_cost?: number;
  failure_reason?: string;
  created_at: string;
  updated_at: string;
  items: OrderItem[];
  steps: StepLog[];
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

function renderFormattedMessage(text: string) {
  if (!text) return null;
  const lines = text.split('\n');

  return lines.map((line, lineIdx) => {
    const trimmed = line.trim();
    const isBullet = trimmed.startsWith('* ') || trimmed.startsWith('- ') || trimmed.startsWith('• ');
    const content = isBullet ? trimmed.substring(2) : line;

    const parts: (string | React.ReactNode)[] = [];
    const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(content)) !== null) {
      if (match.index > lastIndex) {
        parts.push(content.substring(lastIndex, match.index));
      }
      const token = match[0];
      if (token.startsWith('**') && token.endsWith('**')) {
        parts.push(
          <strong key={`${lineIdx}-${match.index}`} style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>
            {token.slice(2, -2)}
          </strong>
        );
      } else if (token.startsWith('`') && token.endsWith('`')) {
        parts.push(
          <code
            key={`${lineIdx}-${match.index}`}
            style={{
              background: 'rgba(56, 189, 248, 0.12)',
              color: '#38bdf8',
              padding: '1px 5px',
              borderRadius: '4px',
              fontFamily: 'monospace',
              fontSize: '0.88em',
              border: '1px solid rgba(56, 189, 248, 0.3)'
            }}
          >
            {token.slice(1, -1)}
          </code>
        );
      }
      lastIndex = regex.lastIndex;
    }

    if (lastIndex < content.length) {
      parts.push(content.substring(lastIndex));
    }

    if (isBullet) {
      return (
        <div key={lineIdx} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', margin: '3px 0' }}>
          <span style={{ color: 'var(--accent-cyan)', fontSize: '0.9em' }}>•</span>
          <div style={{ flex: 1 }}>{parts.length > 0 ? parts : content}</div>
        </div>
      );
    }

    return (
      <div key={lineIdx} style={{ minHeight: trimmed ? undefined : '0.35rem', marginBottom: trimmed ? '0.2rem' : '0' }}>
        {parts.length > 0 ? parts : <span>&nbsp;</span>}
      </div>
    );
  });
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'dispatch' | 'ledger' | 'inventory' | 'carriers'>('dispatch');
  const [isChatDrawerOpen, setIsChatDrawerOpen] = useState<boolean>(false);
  
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

  // Filters
  const [orderSearchQuery, setOrderSearchQuery] = useState<string>('');
  const [orderStatusFilter, setOrderStatusFilter] = useState<string>('ALL');
  const [inventoryWhFilter, setInventoryWhFilter] = useState<string>('ALL');
  const [inventorySearchQuery, setInventorySearchQuery] = useState<string>('');

  // Operator Chat
  const [chatLog, setChatLog] = useState<{ role: 'user' | 'agent'; text: string; meta?: string }[]>([
    {
      role: 'agent',
      text: 'Logistics Autopilot Operator online. Ask about stock levels, track recent shipments, or dispatch orders in natural language.',
      meta: 'Google ADK · gemini-flash-latest · FastMCP'
    }
  ]);
  const [chatInput, setChatInput] = useState<string>('');
  const [chatLoading, setChatLoading] = useState<boolean>(false);

  const showNotification = (msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(null), 4000);
  };

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    showNotification(`Copied ${label} to clipboard!`);
  };

  const fetchInitialData = async () => {
    try {
      const [scenariosRes, invRes, carriersRes, ordersRes, agentRes] = await Promise.all([
        fetch('/api/demo/scenarios'),
        fetch('/api/inventory'),
        fetch('/api/carriers'),
        fetch('/api/shipments'),
        fetch('/api/agent/info')
      ]);

      if (scenariosRes.ok) setScenarios(await scenariosRes.json());
      if (invRes.ok) setInventory(await invRes.json());
      if (carriersRes.ok) setCarriers(await carriersRes.json());
      if (agentRes.ok) setAgentInfo(await agentRes.json());
      if (ordersRes.ok) {
        const ordersData = await ordersRes.json();
        setPastOrders(ordersData);
        if (ordersData.length > 0 && !currentOrder) {
          handleSelectPastOrder(ordersData[0].id);
        }
      }
    } catch (e) {
      console.error('Failed fetching data:', e);
    }
  };

  useEffect(() => {
    fetchInitialData();
  }, []);

  const handleSelectPastOrder = async (orderId: string) => {
    try {
      const res = await fetch(`/api/shipments/${orderId}`);
      if (res.ok) {
        const data = await res.json();
        setCurrentOrder(data);
      }
    } catch (e) {
      console.error('Failed fetching order details:', e);
    }
  };

  const handleApplyScenario = (s: Scenario) => {
    setPrompt(s.prompt);
    setPriority(s.priority);
    setSimulateCarrierFailure(s.simulate_carrier_failure);
    setIdempotencyKey(s.idempotency_key || `IDEMP-${Date.now().toString(36).toUpperCase()}`);
    showNotification(`Loaded scenario: "${s.title}"`);
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

  const handleExecuteShipment = async (e?: React.FormEvent, overridePayload?: any) => {
    if (e) e.preventDefault();
    const promptText = (overridePayload ? overridePayload.raw_prompt : prompt).trim();
    if (!promptText) {
      showNotification('Please enter a natural language dispatch instruction.');
      return;
    }

    setIsLoading(true);
    setActiveTab('dispatch');

    const payload = overridePayload || {
      raw_prompt: promptText,
      priority: priority,
      simulate_carrier_failure: simulateCarrierFailure,
      ...(idempotencyKey ? { idempotency_key: idempotencyKey } : {})
    };

    try {
      const res = await fetch('/api/shipments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Shipment dispatch failed');
      setCurrentOrder(data);
      showNotification(`Order ${data.id} completed with status: ${data.status}`);
      await fetchInitialData();
    } catch (err: any) {
      showNotification(`Error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

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

  const handleToggleCarrierFailure = async (carrierId: string, currentSim: boolean) => {
    try {
      const res = await fetch(`/api/carriers/${carrierId}/toggle_failure`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ simulate_failure: !currentSim })
      });
      if (res.ok) {
        showNotification(`Carrier ${carrierId} failure simulation: ${!currentSim ? 'FORCED 503' : 'NORMAL'}`);
        await fetchInitialData();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleResetDatabase = async () => {
    if (!confirm('Reset logistics database to initial seed state? This restores all stock and carriers.')) return;
    try {
      const res = await fetch('/api/demo/reset', { method: 'POST' });
      if (res.ok) {
        showNotification('Database successfully reset to initial seed state.');
        setCurrentOrder(null);
        await fetchInitialData();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const exportAuditLogJSON = () => {
    if (!currentOrder) return;
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(currentOrder, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `audit-log-${currentOrder.id}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    showNotification(`Exported audit log for ${currentOrder.id}`);
  };

  // KPIs
  const totalOrdersCount = pastOrders.length;
  const completedCount = pastOrders.filter(o => o.status === 'COMPLETED').length;
  const totalStockUnits = inventory.reduce((sum, item) => sum + item.total_stock, 0);
  const totalReservedUnits = inventory.reduce((sum, item) => sum + item.reserved_stock, 0);

  // Filtered Orders
  const filteredOrders = pastOrders.filter(o => {
    const matchesSearch = orderSearchQuery === '' || 
      o.id.toLowerCase().includes(orderSearchQuery.toLowerCase()) ||
      (o.tracking_id && o.tracking_id.toLowerCase().includes(orderSearchQuery.toLowerCase())) ||
      (o.destination_city && o.destination_city.toLowerCase().includes(orderSearchQuery.toLowerCase())) ||
      (o.carrier_id && o.carrier_id.toLowerCase().includes(orderSearchQuery.toLowerCase()));
    const matchesStatus = orderStatusFilter === 'ALL' || o.status === orderStatusFilter;
    return matchesSearch && matchesStatus;
  });

  // Filtered Inventory
  const filteredInventory = inventory.filter(i => {
    const matchesWh = inventoryWhFilter === 'ALL' || i.warehouse_id === inventoryWhFilter;
    const matchesSearch = inventorySearchQuery === '' ||
      i.product_name.toLowerCase().includes(inventorySearchQuery.toLowerCase()) ||
      i.sku.toLowerCase().includes(inventorySearchQuery.toLowerCase()) ||
      i.bin_location.toLowerCase().includes(inventorySearchQuery.toLowerCase());
    return matchesWh && matchesSearch;
  });

  // Workflow Pipeline Graph Nodes
  const pipelineStages = [
    { key: 'ORDER_VALIDATED', label: '1. Validation', desc: 'Catalog & Item Check' },
    { key: 'INVENTORY_RESERVED', label: '2. Inventory', desc: 'Atomic Reservation' },
    { key: 'ITEMS_PICKED', label: '3. Picking', desc: 'Bin Bin Allocation' },
    { key: 'PACKAGING_ASSIGNED', label: '4. Packaging', desc: 'Fragile/Hazmat Certified' },
    { key: 'CARRIER_BOOKED', label: '5. Routing & Carrier', desc: 'Maps v2 & Failover' },
    { key: 'PERSISTED_STATE_VERIFIED', label: '6. Verification', desc: 'State Machine Sealed' }
  ];

  return (
    <div className="app-layout">
      {/* Top Enterprise Header */}
      <header className="top-header">
        <div className="brand-section">
          <div className="brand-icon">
            <Plane size={22} />
          </div>
          <div>
            <div className="brand-title">Logistics Autopilot</div>
            <div className="brand-subtitle">Autonomous Fulfillment & Dispatch Cockpit</div>
          </div>
        </div>

        {/* Telemetry Status Strip */}
        <div className="telemetry-badges">
          <span className="pill-telemetry indigo" title="Multi-Model Google ADK Agent">
            <span className="pulse-dot"></span>
            ADK {agentInfo?.models?.fast || 'gemini-flash'}
          </span>
          <span className="pill-telemetry cyan" title="FastMCP 14 Tools Connected">
            <span className="pulse-dot"></span>
            FastMCP (14 Tools)
          </span>
          <span className="pill-telemetry" title="Google Maps Routes API v2 Active">
            <span className="pulse-dot"></span>
            Maps Routes v2 (Live)
          </span>
          <span className="pill-telemetry" title="SQLite WAL Engine Atomic Transactions">
            <span className="pulse-dot"></span>
            SQLite WAL
          </span>
        </div>

        {/* Header Actions */}
        <div className="header-actions">
          <button className="btn-secondary" onClick={handleResetDatabase} title="Reset DB seed data">
            <RotateCcw size={14} />
            <span>Reset DB</span>
          </button>
          <button 
            className="btn-operator-toggle" 
            onClick={() => setIsChatDrawerOpen(!isChatDrawerOpen)}
            id="open-operator-chat"
          >
            <MessageSquare size={14} />
            <span>AI Operator {isChatDrawerOpen ? '▲' : '▼'}</span>
          </button>
        </div>
      </header>

      {/* Executive KPI Metrics Strip */}
      <section className="kpi-strip">
        <div className="kpi-card">
          <div>
            <div className="kpi-label">Dispatched Fleet Volume</div>
            <div className="kpi-value">{totalOrdersCount} <span style={{ fontSize: '0.9rem', color: '#34d399' }}>({completedCount} sealed)</span></div>
            <div className="kpi-subtext">100% atomic state transitions</div>
          </div>
          <div className="kpi-icon-wrap"><TrendingUp size={20} /></div>
        </div>

        <div className="kpi-card">
          <div>
            <div className="kpi-label">Carrier Failover SLA</div>
            <div className="kpi-value" style={{ color: '#38bdf8' }}>100%</div>
            <div className="kpi-subtext">Autonomous 503 recovery</div>
          </div>
          <div className="kpi-icon-wrap" style={{ color: '#38bdf8' }}><ShieldCheck size={20} /></div>
        </div>

        <div className="kpi-card">
          <div>
            <div className="kpi-label">Available Inventory</div>
            <div className="kpi-value">{totalStockUnits - totalReservedUnits} <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>/ {totalStockUnits} units</span></div>
            <div className="kpi-subtext">{totalReservedUnits} units locked in active bins</div>
          </div>
          <div className="kpi-icon-wrap" style={{ color: '#a5b4fc' }}><Box size={20} /></div>
        </div>

        <div className="kpi-card">
          <div>
            <div className="kpi-label">Routing & API Health</div>
            <div className="kpi-value" style={{ color: '#34d399' }}>OPTIMAL</div>
            <div className="kpi-subtext">Routes v2 + 4 carrier endpoints active</div>
          </div>
          <div className="kpi-icon-wrap" style={{ color: '#34d399' }}><Zap size={20} /></div>
        </div>
      </section>

      {/* Main Tab Navigation */}
      <nav className="tab-navigation">
        <button 
          className={`tab-btn ${activeTab === 'dispatch' ? 'active' : ''}`}
          onClick={() => setActiveTab('dispatch')}
          id="tab-dispatch"
        >
          <Plane size={15} />
          <span>Dispatch Command Center</span>
        </button>
        <button 
          className={`tab-btn ${activeTab === 'ledger' ? 'active' : ''}`}
          onClick={() => setActiveTab('ledger')}
          id="tab-ledger"
        >
          <Layers size={15} />
          <span>Shipments Ledger</span>
          <span className="tab-count">{pastOrders.length}</span>
        </button>
        <button 
          className={`tab-btn ${activeTab === 'inventory' ? 'active' : ''}`}
          onClick={() => setActiveTab('inventory')}
          id="tab-inventory"
        >
          <Package size={15} />
          <span>Multi-Hub Inventory Matrix</span>
          <span className="tab-count">{inventory.length}</span>
        </button>
        <button 
          className={`tab-btn ${activeTab === 'carriers' ? 'active' : ''}`}
          onClick={() => setActiveTab('carriers')}
          id="tab-carriers"
        >
          <Truck size={15} />
          <span>Carrier Fleet Telemetry</span>
          <span className="tab-count">{carriers.length}</span>
        </button>
      </nav>

      {/* TAB 1: DISPATCH COMMAND CENTER */}
      {activeTab === 'dispatch' && (
        <main>
          {/* Preset Test Scenarios */}
          <section className="presets-section">
            <div className="section-title">
              <Sliders size={14} />
              <span>One-Click Validation & Demonstration Scenarios</span>
            </div>
            <div className="presets-grid">
              {scenarios.map((s) => (
                <div 
                  key={s.id} 
                  className="preset-card"
                  onClick={() => handleApplyScenario(s)}
                  id={`scenario-${s.id}`}
                >
                  <div>
                    <div className="preset-header">
                      <span className="preset-name">{s.title}</span>
                      <span className={`badge badge-${s.badge_color}`}>{s.badge}</span>
                    </div>
                    <p className="preset-desc">{s.description}</p>
                  </div>
                  <div className="preset-footer">
                    <span>Load prompt <ArrowRight size={12} style={{ display: 'inline', verticalAlign: 'middle' }} /></span>
                    <button 
                      className="btn-run-preset"
                      disabled={isLoading}
                      onClick={(e) => { e.stopPropagation(); handleRunScenario(s); }}
                    >
                      Run Now
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Autopilot Prompt Dispatch Box */}
          <section className="dispatch-box">
            <form onSubmit={handleExecuteShipment}>
              <div className="dispatch-row">
                <textarea
                  className="prompt-textarea"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Enter natural language dispatch instruction (e.g. 'Ship 2 Industrial LiDAR Scanners and 1 Thermal Core to Chicago overnight')..."
                  rows={2}
                  id="dispatch-prompt-input"
                />
                <button 
                  type="submit" 
                  className="btn-dispatch" 
                  disabled={isLoading || !prompt.trim()}
                  id="btn-dispatch-submit"
                >
                  {isLoading ? (
                    <>
                      <RefreshCw size={20} className="animate-spin" />
                      <span>ORCHESTRATING...</span>
                    </>
                  ) : (
                    <>
                      <Plane size={20} />
                      <span>DISPATCH</span>
                    </>
                  )}
                </button>
              </div>

              <div className="dispatch-options">
                <div className="options-group">
                  <div className="option-field">
                    <span>Priority:</span>
                    <select 
                      className="select-input" 
                      value={priority} 
                      onChange={(e) => setPriority(e.target.value)}
                    >
                      <option value="STANDARD">STANDARD (Ground)</option>
                      <option value="EXPRESS">EXPRESS (Air Priority)</option>
                      <option value="URGENT">URGENT (Critical)</option>
                    </select>
                  </div>

                  <div className="option-field">
                    <span>Idempotency Key:</span>
                    <input 
                      type="text" 
                      className="text-input" 
                      value={idempotencyKey} 
                      onChange={(e) => setIdempotencyKey(e.target.value)}
                      placeholder="Auto-generated if empty"
                      style={{ width: '220px', fontFamily: 'monospace' }}
                    />
                    <button 
                      type="button" 
                      className="btn-secondary" 
                      style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem' }}
                      onClick={() => setIdempotencyKey(`IDEMP-${Date.now().toString(36).toUpperCase()}`)}
                    >
                      New Key
                    </button>
                  </div>
                </div>

                <div className="options-group">
                  <label className="toggle-label" title="Forces primary carrier to return 503 to demonstrate self-healing failover">
                    <div className="toggle-switch">
                      <input 
                        type="checkbox" 
                        checked={simulateCarrierFailure} 
                        onChange={(e) => setSimulateCarrierFailure(e.target.checked)} 
                        id="toggle-simulate-failure"
                      />
                      <span className="toggle-slider"></span>
                    </div>
                    <span style={{ fontSize: '0.78rem', color: simulateCarrierFailure ? '#fbbf24' : 'var(--text-secondary)', fontWeight: simulateCarrierFailure ? 600 : 400 }}>
                      Simulate Carrier 503 Outage
                    </span>
                  </label>
                </div>
              </div>
            </form>
          </section>

          {/* Active Order Overview & Execution Timeline */}
          {currentOrder && (
            <section className="execution-section">
              {/* Visual Pipeline Nodes */}
              <div className="pipeline-graph-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Cpu size={16} color="var(--accent-cyan)" />
                    <span>Autonomous State Machine Execution Graph</span>
                  </div>
                  <span className={`badge ${currentOrder.status === 'COMPLETED' ? 'badge-emerald' : currentOrder.status === 'FAILED' ? 'badge-amber' : 'badge-blue'}`}>
                    {currentOrder.status}
                  </span>
                </div>

                <div className="pipeline-nodes-row">
                  {pipelineStages.map((stage, idx) => {
                    const stepMatch = currentOrder.steps.find(s => s.step_name === stage.key);
                    const isDone = !!stepMatch && stepMatch.status === 'SUCCESS';
                    const isFailed = !!stepMatch && stepMatch.status === 'FAILED';
                    const isRetrying = !!stepMatch && stepMatch.status === 'RETRYING';
                    const isActive = !isDone && !isFailed && currentOrder.status !== 'COMPLETED';

                    return (
                      <React.Fragment key={stage.key}>
                        <div className={`pipeline-node ${isDone ? 'done' : isFailed ? 'failed' : (isRetrying || isActive) ? 'active' : ''}`}>
                          <div className="node-icon-circle">
                            {isDone ? <CheckCircle2 size={18} /> : isFailed ? <XCircle size={18} /> : <span style={{ fontSize: '0.75rem', fontWeight: 600 }}>{idx + 1}</span>}
                          </div>
                          <div className="node-label">{stage.label}</div>
                          <div className="node-subtext">{stage.desc}</div>
                        </div>
                        {idx < pipelineStages.length - 1 && (
                          <div className={`node-connector ${isDone ? 'active' : ''}`} />
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>

              {/* Order Overview Banner */}
              <div className="order-overview-banner">
                <div>
                  <div className="banner-item-label">Order Reference</div>
                  <div className="banner-item-value">
                    <span className="code-pill">
                      {currentOrder.id}
                      <button className="copy-btn" onClick={() => copyToClipboard(currentOrder.id, 'Order ID')}><Copy size={12} /></button>
                    </span>
                  </div>
                </div>

                <div>
                  <div className="banner-item-label">Tracking ID</div>
                  <div className="banner-item-value">
                    {currentOrder.tracking_id ? (
                      <span className="code-pill" style={{ color: '#34d399', borderColor: 'rgba(52, 211, 153, 0.3)', background: 'rgba(52, 211, 153, 0.1)' }}>
                        {currentOrder.tracking_id}
                        <button className="copy-btn" onClick={() => copyToClipboard(currentOrder.tracking_id!, 'Tracking ID')}><Copy size={12} /></button>
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>Pending carrier</span>
                    )}
                  </div>
                </div>

                <div>
                  <div className="banner-item-label">Origin Facility</div>
                  <div className="banner-item-value">
                    <MapPin size={15} color="var(--accent-cyan)" />
                    <span>{currentOrder.warehouse_name || currentOrder.warehouse_id || 'Evaluating...'}</span>
                  </div>
                </div>

                <div>
                  <div className="banner-item-label">Destination</div>
                  <div className="banner-item-value">
                    <MapPin size={15} color="#38bdf8" />
                    <span>{currentOrder.destination_city || 'Pending'}</span>
                  </div>
                </div>

                <div>
                  <div className="banner-item-label">Carrier & Packaging</div>
                  <div className="banner-item-value">
                    <Truck size={15} color="#c084fc" />
                    <span>{currentOrder.carrier_name || 'Autonomous Selection'}</span>
                  </div>
                </div>

                <div>
                  <div className="banner-item-label">Payload Weight & Cost</div>
                  <div className="banner-item-value">
                    <span>{currentOrder.total_weight_kg ? `${currentOrder.total_weight_kg} kg` : '0 kg'} · ${currentOrder.total_cost?.toFixed(2) || '0.00'}</span>
                  </div>
                </div>
              </div>

              {/* Step by Step Execution Timeline */}
              <div className="timeline-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#fff' }}>Autonomous Execution Step Audit & State Evidence</h3>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Every state transition is verified directly against persisted SQLite records.</p>
                  </div>
                  <button className="btn-secondary" onClick={exportAuditLogJSON}>
                    <ExternalLink size={13} />
                    <span>Export Audit JSON</span>
                  </button>
                </div>

                <div className="timeline-list">
                  {currentOrder.steps.map((step, idx) => {
                    const isExpanded = !!expandedPayloads[step.id];
                    const evidence = step.output_payload?.evidence;

                    return (
                      <div 
                        key={step.id || idx} 
                        className={`timeline-step ${step.status === 'SUCCESS' ? 'success' : step.status === 'FAILED' ? 'failed' : 'retrying'}`}
                      >
                        <div 
                          className="step-header"
                          onClick={() => setExpandedPayloads(prev => ({ ...prev, [step.id]: !prev[step.id] }))}
                        >
                          <div className="step-main-info">
                            <span className="step-index-badge">{idx + 1}</span>
                            <span className="step-name">{step.step_name}</span>
                            <span className="step-tool">{step.tool_called}</span>
                            {evidence && (
                              <span className="evidence-chip">
                                <ShieldCheck size={11} />
                                {evidence.check}
                              </span>
                            )}
                          </div>

                          <div className="step-meta">
                            <span>{step.duration_ms}ms</span>
                            <span className={`badge ${step.status === 'SUCCESS' ? 'badge-emerald' : step.status === 'FAILED' ? 'badge-amber' : 'badge-blue'}`}>
                              {step.status}
                            </span>
                            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </div>
                        </div>

                        {isExpanded && (
                          <div className="payload-drawer">
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                              <div>
                                <div style={{ color: 'var(--text-muted)', marginBottom: '0.25rem', fontSize: '0.7rem' }}>INPUT PAYLOAD</div>
                                <pre className="payload-json">{JSON.stringify(step.input_payload, null, 2)}</pre>
                              </div>
                              <div>
                                <div style={{ color: 'var(--text-muted)', marginBottom: '0.25rem', fontSize: '0.7rem' }}>OUTPUT PAYLOAD & PERSISTED EVIDENCE</div>
                                <pre className="payload-json">{JSON.stringify(step.output_payload, null, 2)}</pre>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          )}
        </main>
      )}

      {/* TAB 2: SHIPMENTS & ORDERS LEDGER */}
      {activeTab === 'ledger' && (
        <section className="table-container">
          <div className="table-toolbar">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <input 
                type="text" 
                className="table-search-input"
                placeholder="Search by Order ID, Tracking ID, City..."
                value={orderSearchQuery}
                onChange={(e) => setOrderSearchQuery(e.target.value)}
              />
              <div className="table-filter-pills">
                {['ALL', 'COMPLETED', 'FAILED', 'RETRYING'].map((st) => (
                  <button 
                    key={st}
                    className={`filter-pill ${orderStatusFilter === st ? 'active' : ''}`}
                    onClick={() => setOrderStatusFilter(st)}
                  >
                    {st}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Showing {filteredOrders.length} shipments
            </div>
          </div>

          <table className="enterprise-table">
            <thead>
              <tr>
                <th>Order ID</th>
                <th>Destination</th>
                <th>Origin Hub</th>
                <th>Carrier & Tracking</th>
                <th>Priority</th>
                <th>Cost</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                    No matching orders found in ledger.
                  </td>
                </tr>
              ) : (
                filteredOrders.map((o) => (
                  <tr key={o.id}>
                    <td>
                      <span className="code-pill">
                        {o.id}
                        <button className="copy-btn" onClick={() => copyToClipboard(o.id, 'Order ID')}><Copy size={11} /></button>
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{o.destination_city}</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{o.destination_address}</div>
                    </td>
                    <td>{o.warehouse_id || 'WH-EAST'}</td>
                    <td>
                      <div style={{ fontWeight: 500 }}>{o.carrier_id || 'Pending'}</div>
                      {o.tracking_id && <div style={{ fontSize: '0.7rem', color: '#34d399', fontFamily: 'monospace' }}>{o.tracking_id}</div>}
                    </td>
                    <td>
                      <span className={`badge ${o.priority === 'URGENT' ? 'badge-amber' : o.priority === 'EXPRESS' ? 'badge-blue' : 'badge-emerald'}`}>
                        {o.priority}
                      </span>
                    </td>
                    <td style={{ fontFamily: 'monospace' }}>${o.total_cost?.toFixed(2) || '0.00'}</td>
                    <td>
                      <span className={`badge ${o.status === 'COMPLETED' ? 'badge-emerald' : o.status === 'FAILED' ? 'badge-amber' : 'badge-blue'}`}>
                        {o.status}
                      </span>
                    </td>
                    <td>
                      <button 
                        className="btn-secondary" 
                        style={{ padding: '0.25rem 0.6rem', fontSize: '0.72rem' }}
                        onClick={() => {
                          handleSelectPastOrder(o.id);
                          setActiveTab('dispatch');
                        }}
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </section>
      )}

      {/* TAB 3: MULTI-HUB INVENTORY MATRIX */}
      {activeTab === 'inventory' && (
        <section className="table-container">
          <div className="table-toolbar">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <input 
                type="text" 
                className="table-search-input"
                placeholder="Search SKU, Product, Bin location..."
                value={inventorySearchQuery}
                onChange={(e) => setInventorySearchQuery(e.target.value)}
              />
              <div className="table-filter-pills">
                <button 
                  className={`filter-pill ${inventoryWhFilter === 'ALL' ? 'active' : ''}`}
                  onClick={() => setInventoryWhFilter('ALL')}
                >
                  All Hubs
                </button>
                <button 
                  className={`filter-pill ${inventoryWhFilter === 'WH-EAST' ? 'active' : ''}`}
                  onClick={() => setInventoryWhFilter('WH-EAST')}
                >
                  Alpha Hub (Newark)
                </button>
                <button 
                  className={`filter-pill ${inventoryWhFilter === 'WH-WEST' ? 'active' : ''}`}
                  onClick={() => setInventoryWhFilter('WH-WEST')}
                >
                  Beta Hub (Oakland)
                </button>
              </div>
            </div>

            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              {filteredInventory.length} inventory records
            </div>
          </div>

          <table className="enterprise-table">
            <thead>
              <tr>
                <th>Facility</th>
                <th>SKU & Product</th>
                <th>Bin Location</th>
                <th>Available / Total Stock</th>
                <th>Stock Ratio</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {filteredInventory.map((item, idx) => {
                const ratio = Math.round((item.available_stock / item.total_stock) * 100);
                const isLow = item.available_stock <= 5;
                const isOut = item.available_stock === 0;

                return (
                  <tr key={`${item.warehouse_id}-${item.product_id}-${idx}`}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{item.warehouse_name}</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{item.city}, {item.state}</div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{item.product_name}</div>
                      <div style={{ fontSize: '0.72rem', fontFamily: 'monospace', color: 'var(--accent-cyan)' }}>{item.sku}</div>
                    </td>
                    <td>
                      <span className="code-pill">{item.bin_location}</span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, fontFamily: 'monospace' }}>
                        {item.available_stock} <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>/ {item.total_stock}</span>
                      </div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                        {item.reserved_stock} locked in active order
                      </div>
                    </td>
                    <td style={{ width: '180px' }}>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '3px' }}>{ratio}% available</div>
                      <div className="progress-bar-bg">
                        <div 
                          className="progress-bar-fill" 
                          style={{ 
                            width: `${ratio}%`, 
                            backgroundColor: isOut ? '#f43f5e' : isLow ? '#f59e0b' : '#10b981' 
                          }} 
                        />
                      </div>
                    </td>
                    <td>
                      <span className={`badge ${isOut ? 'badge-amber' : isLow ? 'badge-amber' : 'badge-emerald'}`}>
                        {isOut ? 'OUT OF STOCK' : isLow ? 'LOW STOCK' : 'HEALTHY'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {/* TAB 4: CARRIER FLEET TELEMETRY */}
      {activeTab === 'carriers' && (
        <section className="carrier-grid">
          {carriers.map((c) => (
            <div key={c.id} className="carrier-card">
              <div>
                <div className="carrier-header">
                  <div>
                    <div className="carrier-name">{c.name}</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{c.id} · {c.service_level}</div>
                  </div>
                  <span className={`badge ${c.simulate_failure ? 'badge-amber' : 'badge-emerald'}`}>
                    {c.simulate_failure ? 'OUTAGE (503)' : 'ONLINE'}
                  </span>
                </div>

                <div style={{ margin: '1rem 0' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '4px' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Historical Reliability Rating</span>
                    <span style={{ fontWeight: 600, color: '#fff' }}>{Math.round(c.reliability_rating * 100)}%</span>
                  </div>
                  <div className="progress-bar-bg">
                    <div 
                      className="progress-bar-fill" 
                      style={{ 
                        width: `${Math.round(c.reliability_rating * 100)}%`,
                        backgroundColor: c.reliability_rating > 0.9 ? '#10b981' : '#f59e0b'
                      }} 
                    />
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                  {c.supports_fragile && <span className="badge badge-blue">Fragile Certified</span>}
                  {c.supports_hazmat && <span className="badge badge-purple">Hazmat Certified</span>}
                  <span className="badge badge-emerald">Live Routes v2</span>
                </div>
              </div>

              <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.05)', paddingTop: '0.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Test Fault Injection:</span>
                <button 
                  className={`btn-secondary ${c.simulate_failure ? 'active' : ''}`}
                  onClick={() => handleToggleCarrierFailure(c.id, c.simulate_failure)}
                  style={{ 
                    color: c.simulate_failure ? '#fbbf24' : 'var(--text-secondary)',
                    borderColor: c.simulate_failure ? '#f59e0b' : 'var(--border-subtle)'
                  }}
                >
                  <AlertTriangle size={12} />
                  <span>{c.simulate_failure ? 'Clear Outage' : 'Simulate 503 Outage'}</span>
                </button>
              </div>
            </div>
          ))}
        </section>
      )}

      {/* Slide-over Collapsible AI Operator Drawer */}
      {isChatDrawerOpen && (
        <aside className="chat-drawer" id="operator-chat-drawer">
          <div className="chat-drawer-header">
            <div className="chat-drawer-title">
              <span className="pulse-dot" style={{ background: '#38bdf8' }}></span>
              <span>Autonomous Operator Chat Agent</span>
            </div>
            <div className="chat-drawer-actions">
              <button 
                className="btn-secondary" 
                style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem' }}
                onClick={() => setChatLog([])}
                title="Clear chat"
              >
                Clear
              </button>
              <button 
                className="btn-secondary" 
                style={{ padding: '0.2rem 0.4rem' }}
                onClick={() => setIsChatDrawerOpen(false)}
              >
                <X size={14} />
              </button>
            </div>
          </div>

          <div className="chat-drawer-body">
            {chatLog.map((m, i) => (
              <div key={i} className={`chat-msg ${m.role}`}>
                <div>{renderFormattedMessage(m.text)}</div>
                {m.meta && (
                  <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '0.35rem', fontFamily: 'monospace' }}>
                    {m.meta}
                  </div>
                )}
              </div>
            ))}
            {chatLoading && (
              <div className="chat-msg agent" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <RefreshCw size={14} className="animate-spin" />
                <span>Agent querying FastMCP tools...</span>
              </div>
            )}
          </div>

          <div className="chat-drawer-footer">
            <div className="chat-quick-chips">
              <button className="quick-chip" onClick={() => setChatInput('where is my last shipment?')}>where is my last shipment?</button>
              <button className="quick-chip" onClick={() => setChatInput('how much stock of LiDAR scanners is available?')}>check stock</button>
              <button className="quick-chip" onClick={() => setChatInput('is carrier APEX active right now?')}>check APEX carrier</button>
            </div>

            <form onSubmit={handleChat} className="chat-input-row">
              <input
                className="chat-input-field"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder="Ask or command the agent..."
                disabled={chatLoading}
                id="chat-drawer-input"
              />
              <button 
                type="submit" 
                className="chat-send-btn" 
                disabled={chatLoading || !chatInput.trim()}
                id="chat-drawer-send"
              >
                <Send size={15} />
              </button>
            </form>
          </div>
        </aside>
      )}

      {/* Toast Notification */}
      {notification && (
        <div className="toast-notification">
          <CheckCircle2 size={16} color="#34d399" />
          <span>{notification}</span>
        </div>
      )}
    </div>
  );
}
