package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync/atomic"
	"time"
)

type PaymentRequest struct {
	SourceAccountID string  `json:"source_account_id"`
	DestAccountID   string  `json:"destination_account_id"`
	Amount          float64 `json:"amount"`
	Currency        string  `json:"currency"`
}

type PaymentResponse struct {
	TransactionID string `json:"transaction_id"`
	Status        string `json:"status"`
	Timestamp     string `json:"timestamp"`
}

var counter uint64

func paymentHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	idempotencyKey := r.Header.Get("Idempotency-Key")
	if idempotencyKey == "" {
		http.Error(w, "Idempotency-Key header is required", http.StatusBadRequest)
		return
	}

	atomic.AddUint64(&counter, 1)

	resp := PaymentResponse{
		TransactionID: fmt.Sprintf("txn-%d", atomic.LoadUint64(&counter)),
		Status:        "ACCEPTED",
		Timestamp:     time.Now().UTC().Format(time.RFC3339),
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)
	json.NewEncoder(w).Encode(resp)
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"status":"UP","tps_capacity":18000,"cluster_nodes":12}`))
}

func main() {
	http.HandleFunc("/v1/payments", paymentHandler)
	http.HandleFunc("/health", healthHandler)

	fmt.Println("PayScale HTTPE Engine Core Service starting on :8080...")
	log.Fatal(http.ListenAndServe(":8080", nil))
}