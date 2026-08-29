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
}
type State struct {
	Customer string  `json:"customer"`
	Plan     string  `json:"plan"`
	Sites    []Site  `json:"sites"`
	Events   []Event `json:"events"`
}

var mu sync.Mutex
var st = State{Customer: "Northstar Dev Labs (synthetic demo)", Plan: "Business", Sites: []Site{{ID: "site-1", Handle: "northstar-api", URL: "https://northstar.example", Key: "northstar-demo-key"}}, Events: []Event{
	{Time: "demo", Site: "northstar-api", Type: "auth_failure", Severity: "high", ReportedIP: "203.0.113.17", ObservedIP: "synthetic", Path: "/login", Message: "Synthetic repeated authentication failures"},
	{Time: "demo", Site: "northstar-api", Type: "replay_detected", Severity: "high", ReportedIP: "198.51.100.42", ObservedIP: "synthetic", Path: "/checkout", Message: "Synthetic replay signal"},
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

func main() {
	mux := http.NewServeMux()
	mux.Handle("/", http.FileServer(http.Dir("site")))
	mux.HandleFunc("/api/state", func(w http.ResponseWriter, r *http.Request) { mu.Lock(); defer mu.Unlock(); j(w, st) })
	mux.HandleFunc("/api/owner", func(w http.ResponseWriter, r *http.Request) {
		if !ownerOK(r) {
			http.Error(w, "owner code required", 403)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		j(w, map[string]any{"owner": true, "customer": st.Customer, "plan": st.Plan, "siteCount": len(st.Sites), "eventCount": len(st.Events)})
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
	log.Printf("AegisWatch live defensive beta on %s", addr)
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
	ev := Event{Time: time.Now().UTC().Format(time.RFC3339), Site: s.Handle, Type: q.Type, Severity: q.Severity, ReportedIP: q.SourceIP, ObservedIP: observedIP(r), Path: q.Path, Message: q.Message}
	st.Events = append([]Event{ev}, st.Events...)
	mu.Unlock()
	j(w, map[string]any{"accepted": true, "notice": "IP fields are network-origin telemetry, not human identity attribution."})
}
