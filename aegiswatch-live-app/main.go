package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

const ownerHash = "526c058cfd0a009a3dfbc4e564cd72244d74a265cbf94e865841a43f20c6bc91"
const liveVersion = "0.6"

type Site struct {
	ID     string `json:"id"`
	Handle string `json:"handle"`
	URL    string `json:"url"`
	Key    string `json:"-"`
}
type Event struct {
	Time       string `json:"time"`
	Site       string `json:"site"`
	Type       string `json:"type"`
	Severity   string `json:"severity"`
	ReportedIP string `json:"reportedIP"`
	ObservedIP string `json:"observedIP"`
	Path       string `json:"path"`
	Message    string `json:"message"`
	Simulation bool   `json:"simulation"`
}
type State struct {
	Version  string  `json:"version"`
	Customer string  `json:"customer"`
	Plan     string  `json:"plan"`
	Sites    []Site  `json:"sites"`
	Events   []Event `json:"events"`
}
type Alert struct {
	ID         string `json:"id"`
	Time       string `json:"time"`
	Site       string `json:"site"`
	Category   string `json:"category"`
	Type       string `json:"type"`
	Severity   string `json:"severity"`
	SourceIP   string `json:"sourceIP"`
	ObservedIP string `json:"observedIP"`
	Path       string `json:"path"`
	Message    string `json:"message"`
	Simulation bool   `json:"simulation"`
}

var mu sync.Mutex
var st = State{Version: liveVersion, Customer: "Northstar Dev Labs (synthetic demo)", Plan: "Business", Sites: []Site{{ID: "site-1", Handle: "northstar-api", URL: "https://northstar.example", Key: "northstar-demo-key"}}, Events: []Event{
	{Time: "demo", Site: "northstar-api", Type: "auth_failure", Severity: "high", ReportedIP: "203.0.113.17", ObservedIP: "synthetic", Path: "/login", Message: "Synthetic repeated authentication failures", Simulation: true},
	{Time: "demo", Site: "northstar-api", Type: "replay_detected", Severity: "high", ReportedIP: "198.51.100.42", ObservedIP: "synthetic", Path: "/checkout", Message: "Synthetic replay signal", Simulation: true},
}}

func j(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}
func observedIP(r *http.Request) string {
	if x := strings.TrimSpace(strings.Split(r.Header.Get("X-Forwarded-For"), ",")[0]); x != "" {
		return x
	}
	if x := r.Header.Get("X-Real-IP"); x != "" {
		return x
	}
	return strings.Split(r.RemoteAddr, ":")[0]
}
func ownerOK(r *http.Request) bool {
	s := sha256.Sum256([]byte(r.Header.Get("X-Owner-Code")))
	return hex.EncodeToString(s[:]) == ownerHash
}
func category(e Event) string {
	t := strings.ToLower(e.Type + " " + e.Message)
	switch {
	case strings.Contains(t, "ransom"):
		return "Ransomware Signal"
	case strings.Contains(t, "trojan"):
		return "Trojan Signal"
	case strings.Contains(t, "spyware"):
		return "Spyware Signal"
	case strings.Contains(t, "rootkit"):
		return "Rootkit Signal"
	case strings.Contains(t, "worm"):
		return "Worm Signal"
	case strings.Contains(t, "malware"):
		return "Malware Signal"
	case strings.Contains(t, "credential") || strings.Contains(t, "brute") || strings.Contains(t, "auth_failure"):
		return "Credential Attack"
	case strings.Contains(t, "privilege"):
		return "Privilege Abuse"
	case strings.Contains(t, "replay"):
		return "Replay Attack"
	case strings.Contains(t, "sql") || strings.Contains(t, "injection"):
		return "Injection Attempt"
	case strings.Contains(t, "xss"):
		return "XSS Attempt"
	case strings.Contains(t, "traversal"):
		return "Path Traversal"
	case strings.Contains(t, "integrity"):
		return "Integrity Violation"
	case strings.Contains(t, "malformed"):
		return "Protocol Abuse"
	case strings.Contains(t, "rate"):
		return "Rate / Bot Anomaly"
	case strings.Contains(t, "outbound") || strings.Contains(t, "exfil"):
		return "Suspicious Outbound Activity"
	default:
		return "Security Threat"
	}
}
func threat(e Event) bool {
	s := strings.ToLower(e.Severity)
	if s == "critical" || s == "high" {
		return true
	}
	t := strings.ToLower(e.Type + " " + e.Message)
	for _, k := range []string{"malware", "trojan", "ransom", "spyware", "worm", "rootkit", "credential", "brute", "privilege", "replay", "inject", "xss", "traversal", "malformed", "integrity", "rate", "outbound", "exfil"} {
		if strings.Contains(t, k) {
			return true
		}
	}
	return false
}

func main() {
	mux := http.NewServeMux()
	mux.Handle("/", http.FileServer(http.Dir("site")))
	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		j(w, map[string]any{"ok": true, "version": liveVersion, "service": "AegisWatch Security Live"})
	})
	mux.HandleFunc("/api/state", func(w http.ResponseWriter, r *http.Request) { mu.Lock(); defer mu.Unlock(); j(w, st) })
	mux.HandleFunc("/api/alerts", alerts)
	mux.HandleFunc("/api/owner", func(w http.ResponseWriter, r *http.Request) {
		if !ownerOK(r) {
			http.Error(w, "owner code required", 403)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		j(w, map[string]any{"owner": true, "version": liveVersion, "customer": st.Customer, "plan": st.Plan, "siteCount": len(st.Sites), "eventCount": len(st.Events)})
	})
	mux.HandleFunc("/api/site", createSite)
	mux.HandleFunc("/api/ingest/", ingest)
	mux.HandleFunc("/api/simulate", simulate)
	mux.HandleFunc("/api/scan", scanCode)
	mux.HandleFunc("/api/demo/", demoZip)
	addr := ":" + os.Getenv("PORT")
	if addr == ":" {
		addr = ":10000"
	}
	log.Printf("AegisWatch live defensive beta v%s on %s", liveVersion, addr)
	log.Fatal(http.ListenAndServe(addr, headers(mux)))
}
func headers(n http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		n.ServeHTTP(w, r)
	})
}
func createSite(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "POST", 405)
		return
	}
	if !ownerOK(r) {
		http.Error(w, "owner code required", 403)
		return
	}
	var q struct{ Handle, URL string }
	json.NewDecoder(r.Body).Decode(&q)
	q.Handle = strings.TrimSpace(q.Handle)
	if q.Handle == "" {
		http.Error(w, "handle required", 400)
		return
	}
	key := fmt.Sprintf("aw-%x", sha256.Sum256([]byte(q.Handle+time.Now().String())))
	key = key[:24]
	mu.Lock()
	id := fmt.Sprintf("site-%d", len(st.Sites)+1)
	st.Sites = append(st.Sites, Site{ID: id, Handle: q.Handle, URL: q.URL, Key: key})
	mu.Unlock()
	j(w, map[string]string{"id": id, "siteKey": key, "ingestPath": "/api/ingest/" + id})
}
func ingest(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "POST", 405)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/api/ingest/")
	mu.Lock()
	var s *Site
	for i := range st.Sites {
		if st.Sites[i].ID == id {
			s = &st.Sites[i]
			break
		}
	}
	if s == nil {
		mu.Unlock()
		http.Error(w, "site", 404)
		return
	}
	if r.Header.Get("X-Aegis-Site-Key") != s.Key {
		mu.Unlock()
		http.Error(w, "site key", 403)
		return
	}
	var q struct{ Type, Severity, SourceIP, Path, Message string }
	json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&q)
	ev := Event{Time: time.Now().UTC().Format(time.RFC3339Nano), Site: s.Handle, Type: q.Type, Severity: q.Severity, ReportedIP: q.SourceIP, ObservedIP: observedIP(r), Path: q.Path, Message: q.Message}
	st.Events = append([]Event{ev}, st.Events...)
	if len(st.Events) > 5000 {
		st.Events = st.Events[:5000]
	}
	mu.Unlock()
	j(w, map[string]any{"accepted": true, "notice": "IP fields are network-origin telemetry, not human identity attribution."})
}
func alerts(w http.ResponseWriter, r *http.Request) {
	since := time.Time{}
	if x := r.URL.Query().Get("since"); x != "" {
		since, _ = time.Parse(time.RFC3339Nano, x)
	}
	mu.Lock()
	defer mu.Unlock()
	out := []Alert{}
	for i, e := range st.Events {
		if !threat(e) {
			continue
		}
		if e.Time != "demo" && !since.IsZero() {
			if t, err := time.Parse(time.RFC3339Nano, e.Time); err == nil && !t.After(since) {
				continue
			}
		}
		out = append(out, Alert{ID: fmt.Sprintf("live-%d-%s", i, e.Time), Time: e.Time, Site: e.Site, Category: category(e), Type: e.Type, Severity: e.Severity, SourceIP: e.ReportedIP, ObservedIP: e.ObservedIP, Path: e.Path, Message: e.Message, Simulation: e.Simulation})
		if len(out) >= 100 {
			break
		}
	}
	j(w, map[string]any{"ok": true, "alerts": out})
}
