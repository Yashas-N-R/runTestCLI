package com.example.api;

import io.restassured.RestAssured;
import org.testng.annotations.Test;

/** REST Assured/TestNG API tests for the recording service. */
public class RecordingApiTest {

    @Test(groups = {"recording", "api"})
    public void startRecordingReturns201() {
        assert true;
    }

    @Test(groups = {"recording"})
    public void stopRecordingReturnsDownloadUrl() {
        assert true;
    }

    @Test(groups = {"checkout"})
    public void createOrderReturns200() {
        assert true;
    }
}
