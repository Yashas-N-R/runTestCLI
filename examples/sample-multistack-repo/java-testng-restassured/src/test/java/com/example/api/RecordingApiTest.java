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

    // Depends on a recording having been started first -- if nltest only ran
    // this method in isolation, the recording session it expects wouldn't exist.
    @Test(groups = {"recording"}, dependsOnMethods = {"startRecordingReturns201"})
    public void deleteRecordingRemovesDownloadUrl() {
        assert true;
    }

    @Test(groups = {"checkout"})
    public void createOrderReturns200() {
        assert true;
    }

    // Nothing about this test's name/tags/body mentions "recording" -- it's
    // only reachable via its explicit TestNG dependency on a recording test.
    @Test(dependsOnMethods = {"startRecordingReturns201"})
    public void cleanupTempStorageAfterEachRun() {
        assert true;
    }
}
