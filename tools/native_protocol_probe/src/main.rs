//! Bounded #1513 transport experiment. No gameplay or production LAN endpoint.
//! Only the toolkit's packet, channel, encryption and login codecs are reused.
//! Its modern client/base message layouts are deliberately not used here.

use std::collections::HashMap;
use std::fs;
use std::io::{self, Cursor, Read, Write};
use std::net::{SocketAddr, SocketAddrV4, UdpSocket};
use std::sync::Arc;
use std::time::{Duration, Instant};

use blowfish::Blowfish;
use crypto_common::KeyInit;
use rsa::pkcs1::DecodeRsaPrivateKey;
use rsa::pkcs8::DecodePrivateKey;
use rsa::rand_core::{OsRng, RngCore};
use rsa::{Oaep, PublicKeyParts, RsaPrivateKey};
use serde_json::{Value, json};
use sha1::Sha1;
use wgtk::app::login::element::{LoginRequest, LoginResponse, LoginSuccess};
use wgtk::net::bundle::{Bundle, NextElementReader};
use wgtk::net::codec::Codec;
use wgtk::net::element::{Element, ElementLength};
use wgtk::net::packet::{PACKET_CAP, PACKET_PREFIX_LEN, Packet};
use wgtk::net::proto::Protocol;
use wgtk::net::socket::{decrypt_packet, encrypt_packet};

fn emit(event: &str, data: Value) {
    println!("{}", json!({"event": event, "data": data}));
}

// #1513 datagrams start at the Mercury flags. The toolkit reserves an extra
// modern four-byte prefix internally; it must never go onto this client's wire.
struct NativeSocket {
    socket: UdpSocket,
    encryption: HashMap<SocketAddr, Arc<Blowfish>>,
}

impl NativeSocket {
    fn bind(addr: SocketAddr) -> io::Result<Self> {
        Ok(Self {
            socket: UdpSocket::bind(addr)?,
            encryption: HashMap::new(),
        })
    }

    fn set_recv_timeout(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.socket.set_read_timeout(timeout)
    }

    fn set_encryption(&mut self, addr: SocketAddr, cipher: Arc<Blowfish>) {
        self.encryption.insert(addr, cipher);
    }

    fn recv(&self) -> io::Result<(Packet, SocketAddr)> {
        let mut wire = [0u8; PACKET_CAP];
        let (len, addr) = self.socket.recv_from(&mut wire)?;
        let mut packet = packet_from_wire(&wire[..len])?;
        if let Some(cipher) = self.encryption.get(&addr) {
            packet = decrypt_packet(packet, cipher)
                .map_err(|_| invalid("invalid session encryption"))?;
        }
        Ok((packet, addr))
    }

    fn send_bundle(&self, bundle: &Bundle, addr: SocketAddr) -> io::Result<()> {
        for packet in bundle.iter() {
            let packet = if let Some(cipher) = self.encryption.get(&addr) {
                encrypt_packet(packet.clone(), cipher)
            } else {
                packet.clone()
            };
            self.socket
                .send_to(&packet.slice()[PACKET_PREFIX_LEN..], addr)?;
        }
        Ok(())
    }
}

fn packet_from_wire(wire: &[u8]) -> io::Result<Packet> {
    if !(2..=PACKET_CAP - PACKET_PREFIX_LEN).contains(&wire.len()) {
        return Err(invalid("invalid #1513 datagram length"));
    }
    let mut packet = Packet::new();
    packet.buf_mut()[PACKET_PREFIX_LEN..PACKET_PREFIX_LEN + wire.len()].copy_from_slice(wire);
    packet.set_len(wire.len() + PACKET_PREFIX_LEN);
    Ok(packet)
}

fn decode_login(bytes: &[u8], key: &RsaPrivateKey) -> io::Result<LoginRequest> {
    if bytes.len() < 4 || bytes[..4] != [1, 0, 1, 17] {
        return Err(invalid("login protocol does not match #1513"));
    }
    // 0x7f8eb0 / 0x7f9100 write protocol + RSA stream, with no encrypted bool.
    // Decrypt locally: the toolkit's RSA reader panics on an invalid OAEP block.
    let ciphertext = &bytes[4..];
    if ciphertext.is_empty() || ciphertext.len() % key.size() != 0 {
        return Err(invalid("invalid RSA login ciphertext length"));
    }
    let mut normalized = bytes[..4].to_vec();
    normalized.push(0);
    for block in ciphertext.chunks_exact(key.size()) {
        let plaintext = key
            .decrypt(Oaep::new::<Sha1>(), block)
            .map_err(|_| invalid("invalid RSA login ciphertext"))?;
        normalized.extend(plaintext);
    }
    <LoginRequest as Codec<()>>::read(&mut Cursor::new(normalized), &())
}

#[derive(Clone, Debug)]
struct Raw {
    id: u8,
    length: ElementLength,
    bytes: Vec<u8>,
}

fn fixed(id: u8, bytes: Vec<u8>) -> Raw {
    Raw {
        id,
        length: ElementLength::Fixed(bytes.len() as u32),
        bytes,
    }
}

fn variable(id: u8, bytes: Vec<u8>) -> Raw {
    Raw {
        id,
        length: ElementLength::Variable16,
        bytes,
    }
}

fn bundle_of(messages: &[Raw]) -> Bundle {
    let mut bundle = Bundle::new();
    for message in messages {
        bundle
            .element_writer()
            .write(message.clone(), &message.length);
    }
    bundle
}

fn initial_messages(session_key: u32, tick: u32) -> Vec<Raw> {
    // #1513 0x7e9cc0 consumes offsets 0 and 3; bytes 1..2 are unused.
    let mut frequency = vec![10, 0, 0];
    frequency.extend(tick.to_le_bytes());
    vec![
        fixed(0x00, session_key.to_le_bytes().to_vec()),
        fixed(0x02, frequency),
        fixed(0x04, vec![0]),
    ]
}

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

fn decode_hex(value: &Value) -> io::Result<Vec<u8>> {
    let text = value
        .as_str()
        .ok_or_else(|| invalid("expected hexadecimal string"))?;
    if text.len() % 2 != 0 || !text.is_ascii() {
        return Err(invalid("invalid hexadecimal string"));
    }
    text.as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let a = (pair[0] as char).to_digit(16);
            let b = (pair[1] as char).to_digit(16);
            match (a, b) {
                (Some(a), Some(b)) => Ok((a * 16 + b) as u8),
                _ => Err(invalid("invalid hexadecimal byte")),
            }
        })
        .collect()
}

fn unsigned(value: &Value, name: &str, max: u64) -> io::Result<u64> {
    value[name]
        .as_u64()
        .filter(|n| *n <= max)
        .ok_or_else(|| invalid(format!("missing or out-of-range {name}")))
}

fn floats(value: &Value, name: &str, count: usize) -> io::Result<Vec<u8>> {
    let array = value[name]
        .as_array()
        .filter(|a| a.len() == count)
        .ok_or_else(|| invalid(format!("{name} must contain {count} floats")))?;
    let mut bytes = Vec::new();
    for item in array {
        let number = item
            .as_f64()
            .ok_or_else(|| invalid(format!("invalid {name} float")))? as f32;
        if !number.is_finite() {
            return Err(invalid(format!("non-finite {name}")));
        }
        bytes.extend(number.to_le_bytes());
    }
    Ok(bytes)
}

fn packed_blob(bytes: &mut Vec<u8>, value: &[u8]) -> io::Result<()> {
    if value.len() > 0xff_ffff {
        return Err(invalid("packed blob exceeds uint24"));
    }
    if value.len() < 255 {
        bytes.push(value.len() as u8);
    } else {
        bytes.push(255);
        bytes.extend_from_slice(&(value.len() as u32).to_le_bytes()[..3]);
    }
    bytes.extend_from_slice(value);
    Ok(())
}

fn property_body(fixture: &Value, name: &str) -> io::Result<Vec<u8>> {
    let body = &fixture[name];
    if body["status"] != "encoded" {
        return Err(invalid(format!("{name} is not encoded")));
    }
    let bytes = decode_hex(&body["body_hex"])?;
    if body["byte_length"].as_u64() != Some(bytes.len() as u64) {
        return Err(invalid(format!("{name} byte_length mismatch")));
    }
    Ok(bytes)
}

struct Fixture {
    messages: Vec<Raw>,
}

impl Fixture {
    fn parse(fixture: &Value) -> io::Result<Self> {
        if fixture["schema"] != 1 || fixture["client_build"] != "wot-0.9.22.0.1-cn-1513" {
            return Err(invalid("fixture must target schema 1 / Chinese #1513"));
        }
        let config = &fixture["native_probe"];
        // Synthetic probe identity; optional overrides are explicit experiment inputs.
        let entity_id = if config.get("entity_id").is_some() {
            unsigned(config, "entity_id", u32::MAX.into())? as u32
        } else {
            1
        };
        let type_id = if config.get("avatar_type_id").is_some() {
            unsigned(config, "avatar_type_id", u16::MAX.into())? as u16
        } else {
            2
        };
        let opaque = if config.get("base_opaque_hex").is_some() {
            decode_hex(&config["base_opaque_hex"])?
        } else {
            Vec::new()
        };
        let mut base = Vec::new();
        base.extend(entity_id.to_le_bytes());
        base.extend(type_id.to_le_bytes());
        packed_blob(&mut base, &opaque)?;
        // 0x7e4ae0 -> 0x662c70/0x65c2f0: no modern component-count trailer.
        base.extend(property_body(fixture, "avatar_base")?);
        let mut messages = vec![variable(0x05, base)];

        if let Some(cell) = config.get("cell") {
            let space_id = unsigned(cell, "space_id", u32::MAX.into())? as u32;
            let mut bytes = space_id.to_le_bytes().to_vec();
            bytes.extend((unsigned(cell, "unknown_u16", u16::MAX.into())? as u16).to_le_bytes());
            bytes.extend((unsigned(cell, "vehicle_id", u32::MAX.into())? as u32).to_le_bytes());
            bytes.extend(floats(cell, "position", 3)?);
            let scale = cell["packed_xz_scale"]
                .as_f64()
                .ok_or_else(|| invalid("missing packed_xz_scale"))? as f32;
            if !scale.is_finite() || scale <= 0.0 {
                return Err(invalid("packed_xz_scale must be positive"));
            }
            bytes.extend(scale.to_le_bytes());
            bytes.extend(floats(cell, "direction", 3)?);
            // 0x7e4c00: 38-byte header, then OWN_CLIENT properties.
            bytes.extend(property_body(fixture, "avatar_own_cell")?);
            messages.push(variable(0x06, bytes));

            if let Some(geometry) = config.get("geometry") {
                let entry_id = decode_hex(&geometry["entry_id_hex"])?;
                if entry_id.len() != 8 {
                    return Err(invalid("geometry entry_id must be 8 bytes"));
                }
                let path = geometry["path"]
                    .as_str()
                    .filter(|p| !p.is_empty())
                    .ok_or_else(|| invalid("missing geometry path"))?;
                let mut bytes = space_id.to_le_bytes().to_vec();
                bytes.extend(entry_id);
                // 0x7e1390 -> 0x67ff30: packed path precedes the 4x4 matrix.
                packed_blob(&mut bytes, path.as_bytes())?;
                bytes.extend(floats(geometry, "matrix", 16)?);
                bytes.push(unsigned(geometry, "flag", u8::MAX.into())? as u8);
                messages.push(variable(0x09, bytes));
            }
        } else if config.get("geometry").is_some() {
            return Err(invalid("geometry requires an explicit cell header"));
        }
        // Keep this experiment's messages within ordinary Variable16 framing.
        if messages.iter().any(|m| m.bytes.len() >= u16::MAX as usize) {
            return Err(invalid("fixture message exceeds probe size limit"));
        }
        Ok(Self { messages })
    }
}

impl Element<ElementLength> for Raw {
    fn write_length(&self, _: &ElementLength) -> io::Result<ElementLength> {
        Ok(self.length)
    }
    fn write(&self, writer: &mut dyn Write, _: &ElementLength) -> io::Result<u8> {
        writer.write_all(&self.bytes)?;
        Ok(self.id)
    }
    fn read_length(length: &ElementLength, _: u8) -> io::Result<ElementLength> {
        Ok(*length)
    }
    fn read(reader: &mut dyn Read, length: &ElementLength, len: usize, id: u8) -> io::Result<Self> {
        let mut bytes = vec![0; len];
        reader.read_exact(&mut bytes)?;
        Ok(Self {
            id,
            length: *length,
            bytes,
        })
    }
}

struct ReplyBytes(Vec<u8>);
impl Codec<()> for ReplyBytes {
    fn write(&self, writer: &mut dyn Write, _: &()) -> io::Result<()> {
        writer.write_all(&self.0)
    }
    fn read(reader: &mut dyn Read, _: &()) -> io::Result<Self> {
        let mut bytes = Vec::new();
        reader.read_to_end(&mut bytes)?;
        Ok(Self(bytes))
    }
}

struct PendingLogin {
    cipher: Arc<Blowfish>,
    ip: std::net::IpAddr,
}

struct Peer {
    session_key: u32,
    authenticated: bool,
    enabled: bool,
    fixture_sent: bool,
    last_tick: Instant,
}

struct Probe {
    login: NativeSocket,
    base: NativeSocket,
    login_protocol: Protocol,
    base_protocol: Protocol,
    private_key: RsaPrivateKey,
    advertised_base: SocketAddrV4,
    pending: HashMap<u32, PendingLogin>,
    peers: HashMap<SocketAddr, Peer>,
    fixture: Option<Fixture>,
    started: Instant,
}

impl Probe {
    fn receive_login(&mut self) -> io::Result<()> {
        let (packet, addr) = self.login.recv()?;
        emit(
            "login_packet",
            json!({"peer":addr.to_string(), "bytes":packet.len() - PACKET_PREFIX_LEN}),
        );
        if let Err(error) = packet.read_config_locked_ref() {
            emit(
                "login_framing_error",
                json!({"error":error.to_string(),
                "header": &packet.slice()[..packet.len().min(24)],
                "footer": &packet.slice()[packet.len().saturating_sub(16)..]}),
            );
        }
        let mut channel = self
            .login_protocol
            .accept(packet, addr)
            .map_err(|_| io::Error::other("login packet rejected by Mercury codec"))?;
        let bundles: Vec<_> = channel.pop_bundles().collect();
        for bundle in bundles {
            let mut reader = bundle.element_reader();
            while let Some(next) = reader.next() {
                let NextElementReader::Element(element) = next else {
                    return Err(io::Error::other("unexpected login reply"));
                };
                if element.id() != 0 {
                    return Err(io::Error::other(format!(
                        "unreviewed login element {}",
                        element.id()
                    )));
                }
                let request = element.read::<Raw, _>(&ElementLength::Variable16)?;
                let request_id = request
                    .request_id
                    .ok_or_else(|| io::Error::other("login without request id"))?;
                let data = decode_login(&request.element.bytes, &self.private_key)?;
                // This endpoint is for synthetic local probe sessions only.
                if data.username != "offline_probe" {
                    return Err(io::Error::other("non-probe login rejected"));
                }
                let cipher = Arc::new(
                    Blowfish::new_from_slice(&data.blowfish_key)
                        .map_err(|_| io::Error::other("invalid session cipher"))?,
                );
                let login_key = OsRng.next_u32();
                let response = LoginResponse::Success(LoginSuccess {
                    addr: self.advertised_base.into(),
                    login_key,
                    server_message: "{}".to_owned(),
                });
                let mut out = Bundle::new();
                out.element_writer()
                    .write_reply(response, request_id, cipher.as_ref());
                self.login_protocol
                    .off_channel(addr)
                    .prepare(&mut out, false);
                self.login.send_bundle(&out, addr)?;
                self.pending.insert(
                    login_key,
                    PendingLogin {
                        cipher,
                        ip: addr.ip(),
                    },
                );
                emit(
                    "login_success_sent",
                    json!({"protocol":data.protocol, "peer":addr.to_string()}),
                );
            }
        }
        Ok(())
    }

    fn base_length(id: u8) -> io::Result<ElementLength> {
        // Extracted from #1513 BaseAppExtInterface registrations.
        match id {
            0x00 => Ok(ElementLength::Fixed(5)),
            0x01 => Ok(ElementLength::Fixed(4)),
            0x02 => Ok(ElementLength::Fixed(17)),
            0x03 => Ok(ElementLength::Fixed(22)),
            0x04 => Ok(ElementLength::Fixed(20)),
            0x05 => Ok(ElementLength::Fixed(29)),
            0x06 => Ok(ElementLength::Fixed(0)),
            0x07 | 0x0a => Ok(ElementLength::Fixed(4)),
            0x08 => Ok(ElementLength::Variable16),
            0x09 | 0x0c | 0x0d => Ok(ElementLength::Fixed(0)),
            0x0b => Ok(ElementLength::Fixed(1)),
            0x0e..=0xfe => Ok(ElementLength::Variable16),
            _ => Err(io::Error::other(format!(
                "unreviewed base element {id:#04x}"
            ))),
        }
    }

    fn receive_base(&mut self) -> io::Result<()> {
        let (packet, addr) = self.base.recv()?;
        let mut channel = self
            .base_protocol
            .accept(packet, addr)
            .map_err(|_| io::Error::other("base packet rejected by Mercury codec"))?;
        let bundles: Vec<_> = channel.pop_bundles().collect();
        for bundle in bundles {
            let mut reader = bundle.element_reader();
            while let Some(next) = reader.next() {
                let NextElementReader::Element(element) = next else {
                    return Err(io::Error::other("unexpected base reply"));
                };
                let id = element.id();
                let item = element.read::<Raw, _>(&Self::base_length(id)?)?;
                let bytes = item.element.bytes;
                emit("base_element", json!({"id":id, "bytes":bytes.len()}));
                match id {
                    0x00 => {
                        let login_key = u32::from_le_bytes(bytes[..4].try_into().unwrap());
                        let login = self
                            .pending
                            .get(&login_key)
                            .ok_or_else(|| io::Error::other("unknown probe login key"))?;
                        if login.ip != addr.ip() {
                            return Err(io::Error::other("probe peer changed address"));
                        }
                        let request_id = item
                            .request_id
                            .ok_or_else(|| io::Error::other("base login without request id"))?;
                        let session_key = self
                            .peers
                            .get(&addr)
                            .map(|p| p.session_key)
                            .unwrap_or_else(|| OsRng.next_u32());
                        self.base.set_encryption(addr, Arc::clone(&login.cipher));
                        let mut out = Bundle::new();
                        out.element_writer().write_simple_reply(
                            ReplyBytes(session_key.to_le_bytes().to_vec()),
                            request_id,
                        );
                        self.base_protocol
                            .off_channel(addr)
                            .prepare(&mut out, false);
                        self.base.send_bundle(&out, addr)?;
                        let is_new = !self.peers.contains_key(&addr);
                        self.peers.entry(addr).or_insert(Peer {
                            session_key,
                            authenticated: false,
                            enabled: false,
                            fixture_sent: false,
                            last_tick: Instant::now(),
                        });
                        emit(
                            "base_login_success_sent",
                            json!({"peer":addr.to_string(), "attempt":bytes[4]}),
                        );
                        if is_new {
                            let tick = (self.started.elapsed().as_secs_f64() * 10.0) as u32;
                            let mut out = bundle_of(&initial_messages(session_key, tick));
                            // First native channel bundle follows the off-channel login reply.
                            // Reliable ordering/ACKs work; toolkit retransmission is not implemented.
                            self.base_protocol
                                .channel(addr, None)
                                .prepare(&mut out, true);
                            self.base.send_bundle(&out, addr)?;
                            emit(
                                "native_initial_sent",
                                json!({"peer":addr.to_string(), "ids":[0,2,4]}),
                            );
                        }
                    }
                    0x01 => {
                        let key = u32::from_le_bytes(bytes[..4].try_into().unwrap());
                        if self.peers.get(&addr).map(|p| p.session_key) != Some(key) {
                            return Err(io::Error::other("session key mismatch"));
                        }
                        self.peers.get_mut(&addr).unwrap().authenticated = true;
                        emit(
                            "native_channel_authenticated",
                            json!({"peer":addr.to_string()}),
                        );
                    }
                    0x09 => {
                        if let Some(peer) = self.peers.get_mut(&addr) {
                            if !peer.authenticated {
                                return Err(invalid("enableEntities before authentication"));
                            }
                            peer.enabled = true;
                            emit("native_entities_enabled", json!({"peer":addr.to_string()}));
                            if !peer.fixture_sent {
                                if let Some(fixture) = &self.fixture {
                                    let mut out = bundle_of(&fixture.messages);
                                    self.base_protocol
                                        .channel(addr, None)
                                        .prepare(&mut out, true);
                                    self.base.send_bundle(&out, addr)?;
                                    peer.fixture_sent = true;
                                    emit(
                                        "native_fixture_sent",
                                        json!({"peer":addr.to_string(),
                                        "messages":fixture.messages.iter().map(|m| json!({"id":m.id,"bytes":m.bytes.len()})).collect::<Vec<_>>() }),
                                    );
                                }
                            }
                        }
                    }
                    0x0b => {
                        self.peers.remove(&addr);
                        emit(
                            "native_disconnect",
                            json!({"peer":addr.to_string(), "reason":bytes[0]}),
                        );
                    }
                    0x0e..=0xfe => emit("native_entity_method", json!({"id":id,"payload":bytes})),
                    _ => {}
                }
            }
        }
        Ok(())
    }

    fn ticks(&mut self) -> io::Result<()> {
        for (&addr, peer) in &mut self.peers {
            if peer.last_tick.elapsed() < Duration::from_millis(100) {
                continue;
            }
            peer.last_tick = Instant::now();
            let mut out = Bundle::new();
            let tick = (self.started.elapsed().as_secs_f64() * 10.0) as u32;
            // setGameTime is fixed UINT32 in this build; this also carries ACKs.
            out.element_writer().write(
                Raw {
                    id: 3,
                    length: ElementLength::Fixed(4),
                    bytes: tick.to_le_bytes().to_vec(),
                },
                &ElementLength::Fixed(4),
            );
            self.base_protocol
                .channel(addr, None)
                .prepare(&mut out, false);
            self.base.send_bundle(&out, addr)?;
        }
        Ok(())
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if !(5..=6).contains(&args.len()) {
        return Err("usage: wot-native-protocol-probe LOGIN_IP:PORT BASE_IP:PORT PRIVATE_KEY.pem SECONDS [FIXTURE.json]".into());
    }
    let login_addr: SocketAddr = args[1].parse()?;
    let base_addr: SocketAddrV4 = args[2].parse()?;
    let key_pem = fs::read_to_string(&args[3])?;
    let private_key = RsaPrivateKey::from_pkcs8_pem(&key_pem)
        .or_else(|_| RsaPrivateKey::from_pkcs1_pem(&key_pem))?;
    let seconds: u64 = args[4].parse()?;
    if !(1..=600).contains(&seconds) {
        return Err("duration must be 1..600 seconds".into());
    }
    let fixture = args
        .get(5)
        .map(|path| -> Result<Fixture, Box<dyn std::error::Error>> {
            Ok(Fixture::parse(&serde_json::from_str(
                &fs::read_to_string(path)?,
            )?)?)
        })
        .transpose()?;
    let login = NativeSocket::bind(login_addr)?;
    let base = NativeSocket::bind(base_addr.into())?;
    login.set_recv_timeout(Some(Duration::from_millis(5)))?;
    base.set_recv_timeout(Some(Duration::from_millis(5)))?;
    let mut probe = Probe {
        login,
        base,
        login_protocol: Protocol::new(),
        base_protocol: Protocol::new(),
        private_key,
        advertised_base: base_addr,
        pending: HashMap::new(),
        peers: HashMap::new(),
        fixture,
        started: Instant::now(),
    };
    emit(
        "listening",
        json!({"login":login_addr.to_string(),"base":base_addr.to_string(),"seconds":seconds,"client":"cn_0.9.22_7 #1513",
        "fixture_messages":probe.fixture.as_ref().map(|f|f.messages.len()).unwrap_or(0),"retransmission":false}),
    );
    while probe.started.elapsed() < Duration::from_secs(seconds) {
        for (stage, result) in [
            ("login", probe.receive_login()),
            ("base", probe.receive_base()),
            ("tick", probe.ticks()),
        ] {
            if let Err(error) = result {
                if !matches!(
                    error.kind(),
                    io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut
                ) {
                    emit(
                        "packet_error",
                        json!({"stage":stage,"error":error.to_string()}),
                    );
                }
            }
        }
    }
    emit("finished", json!({"peers":probe.peers.len()}));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn captured_1513_request_framing_has_no_packet_prefix() {
        // Run-05 header/footer, with the RSA ciphertext replaced by zeros.
        let mut wire = vec![1, 0, 0, 4, 1, 21, 55, 0, 0, 0, 0, 1, 0, 1, 17];
        wire.extend([0; 256]);
        wire.extend([2, 0]);
        assert_eq!(wire.len(), 273);
        let mut protocol = Protocol::new();
        let packet = packet_from_wire(&wire).unwrap();
        let mut channel = protocol
            .accept(packet, "127.0.0.1:20013".parse().unwrap())
            .unwrap();
        let bundle = channel.pop_bundles().next().unwrap();
        let mut reader = bundle.element_reader();
        let Some(NextElementReader::Element(element)) = reader.next() else {
            panic!("missing request")
        };
        let request = element.read::<Raw, _>(&ElementLength::Variable16).unwrap();
        assert_eq!(request.request_id, Some(14101));
        assert_eq!(request.element.bytes.len(), 260);
        assert_eq!(&request.element.bytes[..4], &[1, 0, 1, 17]);
        assert!(reader.next().is_none());
        assert!(packet_from_wire(&[0]).is_err());
        assert!(packet_from_wire(&vec![0; PACKET_CAP]).is_err());
    }

    #[test]
    fn rsa_login_omits_modern_encryption_marker() {
        let key = RsaPrivateKey::new(&mut OsRng, 1024).unwrap();
        let request = LoginRequest {
            protocol: 0x11010001,
            username: "offline_probe".into(),
            password: "offline_probe".into(),
            blowfish_key: vec![7; 16],
            context: "x".repeat(200),
            digest: Some([3; 16]),
            nonce: 17,
        };
        let mut modern = Vec::new();
        <LoginRequest as Codec<RsaPrivateKey>>::write(&request, &mut modern, &key).unwrap();
        assert_eq!(modern.remove(4), 1);
        assert!(modern.len() - 4 > key.size());
        let decoded = decode_login(&modern, &key).unwrap();
        assert_eq!(decoded.username, "offline_probe");
        assert_eq!(decoded.blowfish_key, vec![7; 16]);
        assert_eq!(decoded.context, request.context);
        assert_eq!(decoded.nonce, 17);
        modern[0] = 0;
        assert!(decode_login(&modern, &key).is_err());
    }

    #[test]
    fn malformed_rsa_login_returns_error_without_panicking() {
        let key = RsaPrivateKey::new(&mut OsRng, 1024).unwrap();
        let mut wire = vec![1, 0, 1, 17];
        assert_eq!(
            decode_login(&wire, &key).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
        wire.extend(vec![0; key.size()]);
        assert_eq!(
            decode_login(&wire, &key).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
        wire.pop();
        assert_eq!(
            decode_login(&wire, &key).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
    }

    #[test]
    fn session_encryption_keeps_only_mercury_bytes_on_wire() {
        let cipher = Blowfish::new_from_slice(&[7; 16]).unwrap();
        let mut protocol = Protocol::new();
        let mut bundle = bundle_of(&[fixed(1, vec![1, 2, 3, 4])]);
        protocol
            .off_channel("127.0.0.1:20014".parse().unwrap())
            .prepare(&mut bundle, false);
        let original = bundle.iter().next().unwrap();
        let encrypted = encrypt_packet(original.clone(), &cipher);
        let wire = &encrypted.slice()[PACKET_PREFIX_LEN..];
        assert_eq!(wire.len() % 8, 0);
        let decoded = decrypt_packet(packet_from_wire(wire).unwrap(), &cipher).unwrap();
        assert_eq!(
            &decoded.slice()[PACKET_PREFIX_LEN..],
            &original.slice()[PACKET_PREFIX_LEN..]
        );
    }

    fn fixture_json() -> Value {
        json!({"schema":1, "client_build":"wot-0.9.22.0.1-cn-1513",
            "avatar_base":{"status":"encoded","byte_length":3,"body_hex":"112233"},
            "avatar_own_cell":{"status":"encoded","byte_length":2,"body_hex":"aabb"}})
    }

    #[test]
    fn initial_layout_matches_fixed_handlers() {
        let messages = initial_messages(0x44332211, 0x88776655);
        assert_eq!(messages.iter().map(|m| m.id).collect::<Vec<_>>(), [0, 2, 4]);
        assert_eq!(messages[0].bytes, [0x11, 0x22, 0x33, 0x44]);
        assert_eq!(messages[1].bytes, [10, 0, 0, 0x55, 0x66, 0x77, 0x88]);
        assert_eq!(messages[2].bytes, [0]);
    }

    #[test]
    fn base_fixture_stops_after_properties_without_component_trailer() {
        let fixture = Fixture::parse(&fixture_json()).unwrap();
        assert_eq!(fixture.messages.len(), 1);
        assert_eq!(fixture.messages[0].id, 5);
        assert_eq!(
            fixture.messages[0].bytes,
            [1, 0, 0, 0, 2, 0, 0, 0x11, 0x22, 0x33]
        );
    }

    #[test]
    fn cell_and_geometry_use_explicit_headers_and_exact_order() {
        let mut data = fixture_json();
        data["native_probe"] = json!({
            "cell":{"space_id":7,"unknown_u16":258,"vehicle_id":3,
                "position":[1,2,3],"packed_xz_scale":0.5,"direction":[4,5,6]},
            "geometry":{"entry_id_hex":"0102030405060708","path":"spaces/probe",
                "matrix":[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],"flag":0}});
        let fixture = Fixture::parse(&data).unwrap();
        assert_eq!(
            fixture.messages.iter().map(|m| m.id).collect::<Vec<_>>(),
            [5, 6, 9]
        );
        let cell = &fixture.messages[1].bytes;
        assert_eq!(&cell[..10], &[7, 0, 0, 0, 2, 1, 3, 0, 0, 0]);
        assert_eq!(
            &cell[10..22],
            &floats(&data["native_probe"]["cell"], "position", 3).unwrap()
        );
        assert_eq!(&cell[22..26], &0.5_f32.to_le_bytes());
        assert_eq!(&cell[38..], &[0xaa, 0xbb]);
        let geometry = &fixture.messages[2].bytes;
        assert_eq!(&geometry[..12], &[7, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8]);
        assert_eq!(&geometry[12..25], b"\x0cspaces/probe");
        assert_eq!(
            &geometry[25..89],
            &floats(&data["native_probe"]["geometry"], "matrix", 16).unwrap()
        );
        assert_eq!(&geometry[89..], &[0]);
    }

    #[test]
    fn fixture_rejects_missing_or_malformed_fields() {
        let mut data = fixture_json();
        data["avatar_base"]["byte_length"] = json!(4);
        assert!(Fixture::parse(&data).is_err());
        data = fixture_json();
        data["client_build"] = json!("other");
        assert!(Fixture::parse(&data).is_err());
        data = fixture_json();
        data["native_probe"] = json!({"cell":{"space_id":1}});
        assert!(Fixture::parse(&data).is_err());
        data["native_probe"] = json!({"geometry":{}});
        assert!(Fixture::parse(&data).is_err());
        assert!(decode_hex(&json!("0g")).is_err());
        assert!(decode_hex(&json!("0")).is_err());
    }

    #[test]
    fn packed_blob_switches_at_255() {
        let mut bytes = Vec::new();
        packed_blob(&mut bytes, &[1; 254]).unwrap();
        assert_eq!(bytes[0], 254);
        bytes.clear();
        packed_blob(&mut bytes, &[1; 255]).unwrap();
        assert_eq!(&bytes[..4], &[255, 255, 0, 0]);
    }

    #[test]
    fn reliable_initial_then_fixture_has_ordered_sequences_and_ack() {
        let address: SocketAddr = "127.0.0.1:20000".parse().unwrap();
        let mut server = Protocol::new();
        let mut client = Protocol::new();
        let mut initial = bundle_of(&initial_messages(1, 0));
        server.channel(address, None).prepare(&mut initial, true);
        let mut entity = bundle_of(&Fixture::parse(&fixture_json()).unwrap().messages);
        server.channel(address, None).prepare(&mut entity, true);
        let first = initial
            .iter()
            .next()
            .unwrap()
            .read_config_locked_ref()
            .unwrap();
        let second = entity
            .iter()
            .next()
            .unwrap()
            .read_config_locked_ref()
            .unwrap();
        assert!(first.config().on_channel() && first.config().reliable());
        assert_eq!(
            second.config().sequence_num(),
            first.config().sequence_num() + 1
        );
        let mut ready = 0;
        for packet in initial.into_iter().chain(entity.into_iter()) {
            ready += client
                .accept(packet, address)
                .unwrap()
                .pop_bundles()
                .count();
        }
        assert_eq!(ready, 2);
        let mut ack = bundle_of(&[fixed(0x09, Vec::new())]);
        client.channel(address, None).prepare(&mut ack, false);
        assert_eq!(
            ack.iter()
                .next()
                .unwrap()
                .read_config_locked_ref()
                .unwrap()
                .config()
                .cumulative_ack()
                .unwrap()
                .get(),
            2
        );
    }
}
