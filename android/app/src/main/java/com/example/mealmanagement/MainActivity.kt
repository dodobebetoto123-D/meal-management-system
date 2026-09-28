package com.example.mealmanagement

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.weight
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.ui.viewinterop.AndroidView
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.common.InputImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MealScannerApp() }
    }
}

@Composable
private fun MealScannerApp() {
    val context = LocalContext.current
    val preferences = remember {
        context.getSharedPreferences("meal_scanner", Context.MODE_PRIVATE)
    }
    var baseUrl by remember {
        mutableStateOf(preferences.getString("base_url", "http://192.168.1.10:5000") ?: "")
    }
    var savedBaseUrl by remember { mutableStateOf(baseUrl) }
    var result by remember { mutableStateOf<ScanResult?>(null) }
    var lastScanAt by remember { mutableStateOf(0L) }
    var lastUid by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> hasCameraPermission = granted }

    MaterialTheme {
        Column(
            modifier = Modifier.fillMaxSize().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text("급식 QR/바코드 스캐너", style = MaterialTheme.typography.headlineSmall)
            Text("학생 QR/바코드의 문자열을 학생 UID로 서버에 전송합니다.")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it },
                    label = { Text("서버 주소 (예: http://192.168.1.10:5000)") },
                    singleLine = true,
                    modifier = Modifier.weight(1f)
                )
                Button(
                    onClick = {
                        savedBaseUrl = baseUrl.trim().trimEnd('/')
                        preferences.edit().putString("base_url", savedBaseUrl).apply()
                        result = ScanResult("서버 주소를 저장했습니다.", true)
                    },
                    modifier = Modifier.padding(top = 8.dp)
                ) { Text("저장") }
            }
            if (!hasCameraPermission) {
                Text("카메라 권한이 필요합니다.")
                Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }) {
                    Text("카메라 권한 허용")
                }
            } else if (savedBaseUrl.isBlank()) {
                Text("먼저 서버 주소를 저장하세요.")
            } else {
                CameraPreview(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    onBarcode = { uid ->
                        val now = System.currentTimeMillis()
                        if (uid.isBlank() || now - lastScanAt < 2_000L ||
                            (uid == lastUid && now - lastScanAt < 10_000L)
                        ) return@CameraPreview
                        lastScanAt = now
                        lastUid = uid
                        result = ScanResult("처리 중: $uid", true)
                        scope.launch {
                            result = submitScan(savedBaseUrl, uid)
                        }
                    }
                )
            }
            result?.let { scanResult ->
                Text(
                    text = scanResult.message,
                    color = if (scanResult.approved) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.titleMedium
                )
            }
            Spacer(Modifier.height(4.dp))
        }
    }
}

private data class ScanResult(val message: String, val approved: Boolean)

private suspend fun submitScan(baseUrl: String, uid: String): ScanResult =
    withContext(Dispatchers.IO) {
        try {
            val connection = URI("$baseUrl/api/meal/scan").toURL().openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.connectTimeout = 5_000
            connection.readTimeout = 5_000
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.outputStream.use {
                it.write(JSONObject().put("uid", uid).toString().toByteArray(Charsets.UTF_8))
            }
            val body = (if (connection.responseCode in 200..299) connection.inputStream
            else connection.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
            val code = runCatching { JSONObject(body).optString("code") }.getOrDefault("")
            val message = when (code) {
                "approved" -> "승인되었습니다. 맛있게 드세요!"
                "duplicate_same_day" -> "이미 오늘 급식 기록이 있습니다."
                "unregistered_card" -> "등록되지 않은 학생 UID입니다."
                "before_meal_time" -> "아직 배식 시간이 아닙니다."
                "after_meal_time" -> "배식 시간이 끝났습니다."
                else -> "서버 응답 오류 (${connection.responseCode})"
            }
            ScanResult(message, code == "approved")
        } catch (exception: Exception) {
            ScanResult("서버에 연결할 수 없습니다: ${exception.message ?: "주소를 확인하세요"}", false)
        }
    }

@Composable
private fun CameraPreview(modifier: Modifier, onBarcode: (String) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }
    val scanner = remember { BarcodeScanning.getClient() }
    AndroidView(
        modifier = modifier,
        factory = { viewContext ->
            val previewView = PreviewView(viewContext)
            val providerFuture = ProcessCameraProvider.getInstance(viewContext)
            providerFuture.addListener({
                val provider = providerFuture.get()
                val preview = Preview.Builder().build().also {
                    it.surfaceProvider = previewView.surfaceProvider
                }
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(executor) { imageProxy ->
                    val image = imageProxy.image
                    if (image == null) {
                        imageProxy.close()
                        return@setAnalyzer
                    }
                    scanner.process(
                        InputImage.fromMediaImage(image, imageProxy.imageInfo.rotationDegrees)
                    ).addOnSuccessListener { barcodes ->
                        barcodes.firstNotNullOfOrNull { it.rawValue }?.let(onBarcode)
                    }.addOnCompleteListener { imageProxy.close() }
                }
                provider.unbindAll()
                provider.bindToLifecycle(
                    lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis
                )
            }, ContextCompat.getMainExecutor(viewContext))
            previewView
        }
    )
    DisposableEffect(Unit) {
        onDispose {
            scanner.close()
            executor.shutdown()
        }
    }
}
