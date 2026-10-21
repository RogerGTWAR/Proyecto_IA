/* Protocolo de direcciones lógicas 1..24 para Arduino UNO.
   Capa electrónica pendiente: no asigna 24 pines ni energiza salidas.
   Antes de usar hardware, implementar aplicarSalidas() con la expansión elegida.
   Nunca emitir OK si aplicarSalidas() no confirmó la operación.
   Puerto: 9600 baudios, ASCII, un comando terminado en LF.
*/
const byte TOTAL_LEDS = 24;
bool encendidos[TOTAL_LEDS] = {false};
bool salidasConfirmadas = false;
char linea[40];
byte longitud = 0;
bool desbordada = false;

bool aplicarSalidas(const bool *estados) {
  // Punto de integración de la electrónica definitiva, todavía sin configurar.
  (void)estados;
  return false;
}

void aplicarCambio(int led, bool encender, bool todos) {
  bool siguientes[TOTAL_LEDS];
  for (byte i = 0; i < TOTAL_LEDS; ++i)
    siguientes[i] = todos ? false : (i == led - 1 ? encender : encendidos[i]);
  if (!aplicarSalidas(siguientes)) {
    Serial.println(F("ERROR:OUTPUT_NOT_CONFIGURED"));
    return;
  }
  for (byte i = 0; i < TOTAL_LEDS; ++i) encendidos[i] = siguientes[i];
  salidasConfirmadas = true;
  Serial.println(F("OK"));
}

void procesarLinea() {
  if (!strcmp(linea, "PING")) { Serial.println(F("PONG")); return; }
  if (!strcmp(linea, "STATUS")) {
    if (!salidasConfirmadas) { Serial.println(F("ERROR:OUTPUT_NOT_CONFIGURED")); return; }
    Serial.print(F("STATUS:"));
    for (byte i = 0; i < TOTAL_LEDS; ++i) Serial.print(encendidos[i] ? '1' : '0');
    Serial.println(); return;
  }
  if (!strcmp(linea, "ALL:OFF")) { aplicarCambio(0, false, true); return; }
  if (strncmp(linea, "LED:", 4)) { Serial.println(F("ERROR:COMMAND")); return; }
  char *p = linea + 4;
  if (*p < '0' || *p > '9') { Serial.println(F("ERROR:LED")); return; }
  int led = 0;
  byte digitos = 0;
  while (*p >= '0' && *p <= '9') {
    if (++digitos > 2) { Serial.println(F("ERROR:LED")); return; }
    led = led * 10 + (*p++ - '0');
  }
  if (led < 1 || led > TOTAL_LEDS || *p++ != ':') { Serial.println(F("ERROR:LED")); return; }
  if (!strcmp(p, "ON")) aplicarCambio(led, true, false);
  else if (!strcmp(p, "OFF")) aplicarCambio(led, false, false);
  else Serial.println(F("ERROR:COMMAND"));
}

void setup() {
  Serial.begin(9600);
  Serial.println(F("READY"));
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      linea[longitud] = '\0';
      if (desbordada) Serial.println(F("ERROR:LENGTH"));
      else if (longitud) procesarLinea();
      longitud = 0; desbordada = false;
    } else if (c < 32 || c > 126) desbordada = true;
    else if (longitud < sizeof(linea) - 1) linea[longitud++] = c;
    else desbordada = true;
  }
}
