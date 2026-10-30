#!/usr/bin/env bash
# ==============================================================================
# Script Otomatis Persiapan & Menjalankan Lavalink v4.2+ (DAVE Protocol)
# ==============================================================================

set -e

LAVALINK_VERSION="4.2.2"
LAVALINK_URL="https://github.com/lavalink-devs/Lavalink/releases/download/${LAVALINK_VERSION}/Lavalink.jar"

echo "=== Memeriksa Lingkungan Lavalink Server ==="

# 1. Cek apakah Docker terpasang
if command -v docker &> /dev/null; then
    echo "Docker terdeteksi! Menjalankan Lavalink v${LAVALINK_VERSION} via Docker Compose..."
    docker compose up -d
    echo "Lavalink berhasil dijalankan di background pada port 2333."
    echo "Gunakan 'docker compose logs -f' untuk melihat log."
    exit 0
fi

# 2. Cek apakah Java 21 terpasang
if command -v java &> /dev/null; then
    JAVA_VER=$(java -version 2>&1 | head -n 1 | awk -F '"' '{print $2}' | cut -d'.' -f1)
    if [ "$JAVA_VER" -ge 21 ]; then
        echo "Java $JAVA_VER terdeteksi (Memenuhi syarat Java 21+)."
        if [ ! -f "Lavalink.jar" ]; then
            echo "Mengunduh Lavalink.jar v${LAVALINK_VERSION}..."
            curl -L -o Lavalink.jar "${LAVALINK_URL}"
        fi
        echo "Menjalankan Lavalink server..."
        java -jar Lavalink.jar
        exit 0
    else
        echo "Peringatan: Versi Java ($JAVA_VER) di bawah Java 21. Lavalink v4.2+ dan DAVE E2EE memerlukan Java 21."
    fi
fi

echo "======================================================================"
echo "PENTING: Output Suara Discord Memerlukan Protokol DAVE & Java 21!"
echo "Pilih salah satu cara berikut untuk menjalankan Lavalink Server:"
echo ""
echo "Opsi 1 (Direkomendasikan via Docker):"
echo "  Instal Docker & Docker Compose, lalu jalankan:"
echo "  docker compose up -d"
echo ""
echo "Opsi 2 (Manual Java 21):"
echo "  1. Instal OpenJDK 21:"
echo "     Ubuntu/Debian: sudo apt update && sudo apt install openjdk-21-jre-headless"
echo "     Arch Linux:    sudo pacman -S jre21-openjdk-headless"
echo "  2. Unduh Lavalink v${LAVALINK_VERSION}:"
echo "     curl -L -o Lavalink.jar ${LAVALINK_URL}"
echo "  3. Jalankan server:"
echo "     java -jar Lavalink.jar"
echo "======================================================================"
