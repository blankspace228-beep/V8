package main

import (
	"archive/zip"
	"encoding/json"
	"net/http"
	"strings"
	"time"
)

type simReq struct{ Scenario, Site string }

var scenarios = map[string]Event{
	"credential_stuffing": {Type: "auth_failure", Severity: "high", ReportedIP: "192.0.2.44", Path: "/login", Message: "Synthetic credential stuffing signal"},
	"privilege_mismatch":  {Type: "privilege_boundary", Severity: "critical", ReportedIP: "198.51.100.77", Path: "/admin", Message: "Synthetic client/server privilege mismatch"},
	"replay":              {Type: "replay_detected", Severity: "high", ReportedIP: "203.0.113.91", Path: "/api/payment", Message: "Synthetic replay signal"},
	"sql_injection":       {Type: "input_attack_signature", Severity: "high", ReportedIP: "192.0.2.155", Path: "/search", Message: "Synthetic SQL injection signature"},
	"xss":                 {Type: "input_attack_signature", Severity: "medium", ReportedIP: "198.51.100.77", Path: "/comment", Message: "Synthetic XSS signature"},
	"path_traversal":      {Type: "path_traversal", Severity: "high", ReportedIP: "203.0.113.91", Path: "/files", Message: "Synthetic path traversal signature"},
	"malformed":           {Type: "malformed_protocol", Severity: "medium", ReportedIP: "192.0.2.44", Path: "/api", Message: "Synthetic malformed frame"},
	"integrity":           {Type: "code_integrity", Severity: "critical", ReportedIP: "198.51.100.77", Path: "/deploy", Message: "Synthetic code integrity change"},
	"malware":             {Type: "malware_like", Severity: "critical", ReportedIP: "203.0.113.91", Path: "uploaded-code", Message: "Synthetic malware-like uploaded-code signal"},
	"rate_spike":          {Type: "rate_spike", Severity: "medium", ReportedIP: "192.0.2.155", Path: "/api", Message: "Synthetic request-rate spike"},
}

func simulate(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "POST", 405)
		return
	}
	var q simReq
	json.NewDecoder(r.Body).Decode(&q)
	names := []string{q.Scenario}
	if q.Scenario == "full" || q.Scenario == "" {
		names = []string{"credential_stuffing", "privilege_mismatch", "replay", "sql_injection", "xss", "path_traversal", "malformed", "integrity", "malware", "rate_spike"}
	}
	mu.Lock()
	site := q.Site
	if site == "" && len(st.Sites) > 0 {
		site = st.Sites[0].Handle
	}
	n := 0
	for _, name := range names {
		ev, ok := scenarios[name]
		if !ok {
			continue
		}
		ev.Time = time.Now().UTC().Format(time.RFC3339)
		ev.Site = site
		ev.ObservedIP = "synthetic"
		st.Events = append([]Event{ev}, st.Events...)
		n++
	}
	mu.Unlock()
	j(w, map[string]any{"generated": n, "notice": "Synthetic telemetry only. No traffic was sent to any outside website or IP address."})
}

type finding struct {
	Severity string `json:"severity"`
	Rule     string `json:"rule"`
	Message  string `json:"message"`
	Fix      string `json:"fix"`
}

func scanCode(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "POST", 405)
		return
	}
	var q struct{ Code string }
	json.NewDecoder(r.Body).Decode(&q)
	c := strings.ToLower(q.Code)
	fs := []finding{}
	add := func(ok bool, sev, rule, msg, fix string) {
		if ok {
			fs = append(fs, finding{sev, rule, msg, fix})
		}
	}
	add(strings.Contains(c, "insecureskipverify: true") || strings.Contains(c, "verify=false"), "high", "TLS_VERIFY_DISABLED", "TLS verification appears disabled.", "Enable certificate verification and validate trust roots.")
	add(strings.Contains(c, "eval(") || strings.Contains(c, "exec("), "high", "DYNAMIC_EXECUTION", "Dynamic code execution detected.", "Replace dynamic execution with explicit parsing/dispatch.")
	add(strings.Contains(c, "select ") && strings.Contains(c, "+"), "high", "SQL_CONCAT", "SQL appears dynamically concatenated.", "Use parameterized queries.")
	add(strings.Contains(c, "access-control-allow-origin: *") || strings.Contains(c, "cors('*')"), "medium", "CORS_WILDCARD", "Wildcard CORS detected.", "Allow only required origins.")
	add(strings.Contains(c, "api_key=") || strings.Contains(c, "secret=") || strings.Contains(c, "password="), "critical", "HARDCODED_SECRET", "Possible hard-coded secret.", "Move secrets to a secret manager/environment and rotate exposed values.")
	add(strings.Contains(c, "md5(") || strings.Contains(c, "sha1("), "medium", "WEAK_HASH", "Weak hash use detected.", "Use a modern password KDF or SHA-256+ where appropriate.")
	j(w, map[string]any{"findings": fs, "count": len(fs), "mode": "defensive static demo analyzer"})
}

var packs = map[string]map[string]string{
	"basic":      {"config.py": "DEBUG=True\nAPI_KEY=demo-only-secret\n", "tls.go": "tls.Config{InsecureSkipVerify: true}\n", "renderer.js": "eval(userInput)\n"},
	"pro":        {"db.py": "query = 'SELECT * FROM users WHERE id=' + user_id\n", "cors.js": "res.setHeader('Access-Control-Allow-Origin: *')\n", "hash.py": "hashlib.md5(data).hexdigest()\n"},
	"business":   {"README.txt": "INERT defensive fixture: encoded execution / download-and-execute / client privilege trust indicators only.\n", "trust.js": "const role = request.body.role; // demo client-trust boundary risk\n"},
	"enterprise": {"README.txt": "Synthetic multi-service enterprise defensive test pack. No working malware or targets.\n", "gateway.txt": "CORS wildcard fixture\n", "auth.txt": "client role trust fixture\n", "runtime.json": "{\"event\":\"replay_detected\",\"sourceIP\":\"203.0.113.91\"}\n"},
	"clean":      {"README.txt": "Secure baseline comparison pack.\n", "tls.txt": "certificate verification enabled\n", "db.txt": "parameterized query example\n"},
}

func demoZip(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(r.URL.Path, "/api/demo/")
	name = strings.TrimSuffix(name, ".zip")
	p, ok := packs[name]
	if !ok {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", "attachment; filename=AegisWatch_"+name+"_Demo.zip")
	z := zip.NewWriter(w)
	for fn, body := range p {
		f, _ := z.Create(fn)
		f.Write([]byte(body))
	}
	z.Close()
}
